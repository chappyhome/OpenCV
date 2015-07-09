#!/usr/bin/python

# simple motion detection based on Adrian Rosebrock's code at
# http://www.pyimagesearch.com/2015/05/25/basic-motion-detection-and-tracking-with-python-and-opencv/
# additions to compute velocity and distance-travelled by J.Beale 7/7/2015

# specific camera view cal points: 640 or 1296 pixels across. Vx(corr) = Vx * f * (Xmax - x)
# (486/640), -25.5    (35/640), -13.4      dX = (486-35)/640= 0.7047 : 25.5/13.3 = 1.917   f=2.72
# (591/640), 28.7     (209/640), 18.25     dX = (591-209)/640= 0.597 : 28.7/18.25=1.573    f=2.63
# (1002/1296), -42.8  (52/1296), -21.67    dX = (1002-52)/1296=0.733 : 42.8/21.67=1.976    f=2.69
# (1148/1296), 45     (528/1296), 32       dX = (1148-528)/1296=0.478: 45/32=1.406         f=2.94

# import the necessary packages
import argparse
import datetime
import imutils
import time
import cv2
import numpy as np

kernel5 = np.array([[0, 1, 1, 1, 0],
                    [1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1],
                    [0, 1, 1, 1, 0]]).astype(np.uint8)  # 5x5 convolution kernel, round-ish
                    
maxObjects = 3                               # how many objects to detect track at once                    
x = np.float32(np.zeros(maxObjects))         # x corner coordinates  
y = np.float32(np.zeros(maxObjects))         # y corner coordinates                     
a = np.float32(np.zeros(maxObjects))         # object contour area                   
ao = np.float32(np.ones(maxObjects))         # area on last frame                     
xc = np.float32(np.zeros(maxObjects))        # x center coordinates  
yc = np.float32(np.zeros(maxObjects))        # y center coordinates                     
w = np.float32(np.zeros(maxObjects))         # object width
h = np.float32(np.zeros(maxObjects))         # object height
xstart = np.float32(np.zeros(maxObjects))    # x position when object first tracked
xdist = np.float32(np.zeros(maxObjects))     # x distance travelled
xo = np.float32(np.zeros(maxObjects))        # x last frame center coordinates  
wo = np.float32(np.zeros(maxObjects))        # x width previous value 
xvel = np.float32(np.zeros(maxObjects))      # delta-x per frame
xvelFilt = np.float32(np.zeros(maxObjects))  # filtered delta-x per frame
yvelFilt = np.float32(np.zeros(maxObjects))  # filtered delta-y per frame
oxvel = np.float32(np.zeros(maxObjects))     # old x velocity from previous frame
dXWidth = np.float32(np.zeros(maxObjects))     # change in X width per frame
ystart = np.float32(np.zeros(maxObjects))    # y position when object first tracked
ydist = np.float32(np.zeros(maxObjects))     # y distance travelled
yo = np.float32(np.zeros(maxObjects))        # y last frame center coordinates  
yvel = np.float32(np.zeros(maxObjects))      # delta-y per frame
                    
#procWidth = 640   # processing width (x resolution) of frame
procWidth = 1296   # processing width (x resolution) of frame
rf = (procWidth / 320.0) # resolution scaling factor relative to 320 pixels across
displayWidth = 320 # width of output window display
fracF = 0.15       # adaptation fraction of background on each frame 
#GB = int((rf*15)+0.9)+1      # gaussian blur size
GB = 15
psF1 = 1.7     # normalized x-axis perspective correction for LHS of screen
psF2 = 1.2     # normalized x-axis perspective correction factor  for RHS of screen
dilateIter = int(rf)     # number of iterations of dilation (join adjacent areas)
fracS = 0.03       # adaptation during motion event
noMotionCount = 0  # how many consecutive frames of no motion detected
motionCount = 0    # how many frames of consecutive motion
noMotionLimit = 5  # how many no-motion frames before start adapting
maxVel = rf*20     # fastest real-life reasonable velocity (not some glitch)
maxDVel = rf*2.0   # maximum change in velocity per frame (~ acceleration)
maxDXWidth = rf*20 # maximum change in X width per frame
vfilt = 0.5        # stepwise velocity filter factor (low-pass filter) 
minXPos = rf*12     # minimum valid x position for valid event track
xdistThresh = rf*15   # how many pixels an object must travel before it is counted as an event
ydistThresh = rf*5    # how many pixels an object must travel before it is counted as an event
xvelThresh = rf*1     # how fast object is moving along x before considered an event
yvelThresh = rf*0.3   # how fast object is moving along y before considered an event
yCropFrac = 14      # crop off this (1/x) fraction of the top of frame (time/date string)
fCount = 0          # count total number of frames
font = cv2.FONT_HERSHEY_SIMPLEX              # for drawing text
 
# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-v", "--video", help="path to the video file")
ap.add_argument("-a", "--min-area", type=int, default=(rf*rf*500), help="minimum area size")
args = vars(ap.parse_args())
 
# if the video argument is None, then we are reading from webcam
if args.get("video", None) is None:
    camera = cv2.VideoCapture(0)
    time.sleep(4)
 
# otherwise, we are reading from a video file
else:
    camera = cv2.VideoCapture(args["video"])

record = False  # should we record video output?
voname = 'track-out4.avi' # name of video output to save

# initialize the first frame in the video stream
averageFrame = None
slowFrame = None
motionDetect = False
tStart = time.clock()  # record start time for duration measure
minVal = 0
maxVal = 0
minLoc = -1
maxLoc = -1

(grabbed, frame) = camera.read()   # get very first frame
if grabbed:                            # did we actually get a frame?
  ys,xs,chan = frame.shape
  ycrop = ys/yCropFrac  # fraction of top edge of frame to crop off
  cv2.rectangle( frame, ( 0,0 ), ( xs, ycrop), ( 0,0,0 ), -1, 8 ) # overlay black rectangle (cover datestamp)
  
  frame = imutils.resize(frame, width=procWidth)  # resize to specified dimensions
  ysp,xsp,chan = frame.shape
  yspLim = 2*ysp/3                 # allowable sum of heights of detected objects
  gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)  # convert to greyscale
  gray = cv2.GaussianBlur(gray, (GB,GB), 0)  # Amount of Gaussian blur is a critical value
  # print "xp, yp, xwidth, xvel, xdist"    # headers for CSV output
  
  averageFrame = gray
  slowFrame = gray
  if (record):
    video = cv2.VideoWriter(voname, -1, 25, (xsp,ysp))  # open output video to record
  
# loop over the frames of the video
# ===========================================================================
while grabbed:
    (grabbed, frame) = camera.read()
    if not grabbed:
        break

    fCount += 1                            # count total number of frames
    text = "Static"

#    if (fCount%2 == 0):      # skip even frames, this runs 2x faster
#      continue    

    cv2.rectangle( frame, ( 0,0 ), ( xs, ycrop), ( 0,0,0 ), -1, 8 ) # black rectangle at top

    # resize the frame, convert it to grayscale, and blur it
    frame = imutils.resize(frame, width=procWidth)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (GB, GB), 0)  # Amount of Gaussian blur is a critical value

    if (noMotionCount > noMotionLimit):
        averageFrame =  cv2.addWeighted(gray, fracF, averageFrame, (1.0 - fracF), 0)
        
    if (motionCount == 1):      # reset current background to slowly-changing base background
      averageFrame = slowFrame
      # print "# MotionStart"
      # hsum = h[0] + h[1] + h[2]   # sum of y-heights of first three objects

    if ((noMotionCount > 30) and maxVal < 30):     # reset background when quiet, or too much 
      averageFrame = gray        # hard reset to average filter; throw away older samples
      slowFrame = averageFrame
      noMotionCount = 0
      # print "# Bkgnd reset"
      
    frameDelta = cv2.absdiff(averageFrame, gray)  # difference of this frame from average background
    thresh = cv2.threshold(frameDelta, 25, 255, cv2.THRESH_BINARY)[1]
    (minVal, maxVal, minLoc, maxLoc) = cv2.minMaxLoc(frameDelta)
    # print "max = %d  %d,%d" % (maxVal, w[1], h[1])
    
    thresh = cv2.dilate(thresh,kernel5,iterations = dilateIter) # dilate to join adjacent regions, with larger kernel
    (_, cnts, hierarchy) = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
 
    motionDetect = False         # we have not yet found motion in this frame
    motionStart = False          # haven't just started to detect a motion
    i = -1                        # count of detected objects
    w = np.float32(np.zeros(maxObjects))         # reset object width
    h = np.float32(np.zeros(maxObjects))         # reset object height
    
    for c in cnts:     # loop over the detected object-groups (contours) in arbitrary order
        area = cv2.contourArea(c)  # contour area of detected object
        if area < args["min_area"]: # ignore too-small objects
            continue
        xt, yt, wt, ht = cv2.boundingRect(c)
        yct = yt + ht/2
        if ((ysp-yct) < (ysp*0.65)):  # area of interest is at top; ignore lower portion of frame
            continue
        if (xt < minXPos):  # limit valid region to x values to the right of this boundary
            continue
            
        i += 1  # found a large-enough object...
        if (i >= maxObjects):  # ignore too-many objects
            continue
        
        (x[i], y[i], w[i], h[i]) = (xt, yt, wt, ht)  # bounding box (x,y) and (width, height)
        a[i] = area
        xc[i] = x[i] + w[i]/2  # (x,y) center coords of this contour
        yc[i] = y[i] + h[i]/2
        xvel[i] = x[i] - xo[i]  # delta-x since previous frame
        yvel[i] = (y[i]+h[i]) - yo[i]  # delta-x since previous frame

        if xvelFilt[i] == 0.0:  # is this the initial value?
            xvelFilt[i] = xvel[i]  # reset value without averaging  
            oxvel[i] = xvelFilt[i] # set initial acceleration to zero
            wo[i] = w[i]           # reset old X width
        else:
            xvelFilt[i] = (vfilt * xvel[i]) + (1.0-vfilt)*xvelFilt[i]  # find the rolling average
        if yvelFilt[i] == 0.0:  # initial value?
            yvelFilt[i] = yvel[i]  # reset value without averaging        
        else:
            yvelFilt[i] = (vfilt * yvel[i]) + (1.0-vfilt)*yvelFilt[i]  # rolling average

        dXWidth[i] = w[i] - wo[i]   # ratio of current X width to previous
            
        # big change in velocity, size, or acceleration = new object
        avel = xvelFilt[i] - oxvel[i]  # change in velocity since last frame
        if (abs(xvel[i]) > maxVel) or (abs(yvel[i]) > maxVel) \
              or (abs(avel) > maxDVel) or (abs(dXWidth[i]) > maxDXWidth):  
           xvel[i] = 0
           yvel[i] = 0
           xstart[i] = x[i]  # reset x starting point to 'here'
           ystart[i] = (y[i]+h[i])  # reset x starting point to 'here'
           xvelFilt[i] = 0  # reset filtered velocity
           yvelFilt[i] = 0
           print "# RESET : big change -> new object"
           print "# %d: xv:%5.1f yv:%5.1f av:%5.1f dXW:%5.1f " % (i, xvel[i], yvel[i], avel, dXWidth[i])
           
        xdist[i] = x[i] - xstart[i] # x distance this blob has travelled so far
        ydist[i] = (y[i]+h[i]) - ystart[i] # y distance this blob has travelled so far
        xo[i] = x[i]  # remember this coordinate for next frame
        yo[i] = (y[i]+h[i])  # remember this coordinate for next frame
        ao[i] = a[i]   # remember old object bounding-contour area
        wo[i] = w[i]   # remember old width
        oxvel[i] = xvelFilt[i]  # remember old velocity
        
        bcolor = (100,100,100)  # OpenCV color triplet is (Blue,Green,Red) values
        tstring = "%5.2f" % (xvelFilt[i])
        tstring2 = "%4.0f" % (xdist[i])
        if ((abs(xdist[i]) > xdistThresh) or (abs(ydist[i]) > ydistThresh)) \
         and ((abs(xvelFilt[i]) > xvelThresh) or (abs(yvelFilt[i] > yvelThresh))):
            motionDetect = True
            bcolor = (0,0,255)  # Blue,Green,Red    
            if (motionCount > 1):  # ignore first frame of motion, often spurious            
              cv2.putText(frame,tstring,(int(x[i]),int(yc[i]+30*rf)), font, 0.5,bcolor,2,cv2.LINE_AA)
              cv2.putText(frame,tstring2,(int(x[i]),int(yc[i]+40*rf)), font, 0.5,bcolor,2,cv2.LINE_AA)
              xf = ((1.0*procWidth - x[i])/procWidth)  # fractional distance across screen, 0 = RHS
              perspecF = (psF1 * xf) + (psF2 * (1.0-xf))
              xvelC = xvelFilt[i] * (1.0 + (perspecF * xf ))  # geometric perspective correction
              if (i==0):  # assume 1st contour is the good one
                print "%5.1f,%5.1f, %5.1f,  %5.2f, %5.0f, %5.1f" % \
                 (x[i], ysp-(y[i]+h[i]), w[i], xvelC, xdist[i], dXWidth[i])

        cv2.rectangle(frame, (x[i], y[i]), (x[i] + w[i], y[i] + h[i]), bcolor, 2)  # draw box around event
        nstring = "%d" % (i+1)
        cv2.putText(frame,nstring,(int(xc[i]),int(yc[i])), font, 1,bcolor,2,cv2.LINE_AA) # object number label

    if (motionDetect):
      noMotionCount = 0
      motionCount += 1
    else:                  # no motion found anywhere
      if (noMotionCount == 0) and (motionCount != 0):  # first no-motion frame?
        print "# motion end after %d frames" % motionCount
      xvelFilt = np.float32(np.zeros(maxObjects))  # reset average motion to 0
      yvelFilt = np.float32(np.zeros(maxObjects)) 
      oxvel = np.float32(np.zeros(maxObjects))     # old x velocity from previous frame
      noMotionCount += 1
      motionCount = 0

    if (displayWidth != procWidth):  
      frame2 = imutils.resize(frame, width=displayWidth)
    else:
      frame2 = frame.copy()
      
    cv2.imshow("Video", frame2)             # original video with detected rectangle and info overlay
    # cv2.imshow("Thresh", thresh)           # thresholded output (binary black and white)
    # cv2.imshow("Frame Delta", frameDelta)  # pre-threshold frame differences (grey)

    if (record):
        video.write(frame)                    # save frame of output video

    key = cv2.waitKey(1) & 0xFF
 
    # Quit on 'esc' or q key
    if key == ord("q") or (key == 27):
        break
    if key == ord(" "):  # space to enter pause mode: wait until spacebar pressed again
      key = 0x00
      while key != ord(" "):
         key = cv2.waitKey(1) & 0xFF  

# Finish: print duration and shut down         
dur = time.clock() - tStart
print "# EOF frames = %d  dur = %5.3f fps=%5.1f" % (fCount, dur, fCount/dur)  # timing information

# cleanup the camera and close any open windows
if (record):
    video.release()    
camera.release()
cv2.destroyAllWindows()
        
