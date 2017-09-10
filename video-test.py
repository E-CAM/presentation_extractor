#!/usr/bin/env python
"""testing of video presentation slides extractor"""

import sys

import numpy as np
import cv2

tomask = {
    'x': 1018,
    'y': 0,
    'b': 342,
    'h': 194,
}

tomask['x2'] = tomask['x'] + tomask['b']
tomask['y2'] = tomask['y'] + tomask['h']

cap = cv2.VideoCapture(sys.argv[1])
if not cap.isOpened():
    print("Failed to open file")

fps = cap.get(cv2.CAP_PROP_FPS)
print("FPS: %s" % fps)
nFrames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print("Frames: %s" % nFrames)

hist = None
prev_hist = None

pixel_count = None

last_frame_black = False
black_frame_start = -1

# Do first frame outside loop
ret, frame = cap.read()
print(frame.size)

prev_frame = np.zeros((frame.shape[0], frame.shape[1]), np.uint8)
prev_d_colors = 0

frame_hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
#prev_hist = cv2.calcHist([frame_hsv], [0, 1], None, [180, 256], [0, 180, 0, 256])
#prev_hist = cv2.calcHist([frame_hsv], [0, 1], None, [180, 256], [0, 180, 0, 256])  #.flatten()
prev_hist = cv2.calcHist([frame_hsv], [0, 1, 2], None, [180, 256, 256], [0, 180, 0, 256, 0, 256])  #.flatten()
#prev_hist = prev_hist / sum(prev_hist)
prev_hist = prev_hist / np.sum(prev_hist)
#prev_hist = cv2.normalize(prev_hist)

prev_hit = False

THRESHOLD = 0.48

# Start processing from the second frame
while True:
    frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
    time_idx = cap.get(cv2.CAP_PROP_POS_MSEC)
    ret, frame = cap.read()
    if not ret:
        break

    frame[tomask['y']:tomask['y2'], tomask['x']:tomask['x2']] = [0, 0, 0]
#    cv2.imwrite('frame_%06d.png' % frame_idx, frame)
    frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # METHOD #1: find the number of pixels that have (significantly) changed since the last frame
    frame_diff = cv2.absdiff(frame_gray, prev_frame)
    _, frame_thres = cv2.threshold(frame_diff, 115, 255, cv2.THRESH_BINARY)
    d_colors = float(np.count_nonzero(frame_thres)) / frame_gray.size

#    print(frame_thres.shape)
#    print(d_colors)


#    if abs(prev_d_colors-d_colors) > 0.01 and not prev_hit:
#        print("Got a hit: %s" % frame_idx)
#        cv2.imwrite('frame_gray_d_%06d.png' % frame_idx, frame)
#        prev_hit = True
#    else:
#        prev_hit = False

#    hist = cv2.calcHist([frame_gray],[0],None,[256],[0,256])

#    frame_hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
#    hist = cv2.calcHist([frame_hsv], [0, 1, 2], None, [180, 256, 256], [0, 180, 0, 256, 0, 256])  #.flatten()
#    print(hist.shape)
#    print(hist)
#    break
#    hist = hist.flatten()
#    hist = hist / np.sum(hist)
#    d_hist = 1 - cv2.compareHist(hist, prev_hist, cv2.HISTCMP_INTERSECT)
#    d_hist2 = cv2.compareHist(hist, prev_hist, cv2.HISTCMP_CHISQR)

    #if (0.4*d_colors + 0.6*d_hist) >= THRESHOLD:
    if d_colors > 0.01:
        print("Got a hit: %s" % frame_idx)
#        cv2.imwrite('frame_combined_%06d.png' % frame_idx, frame)

#    if d_hist2 > 0.01:
#        print("Got a hit2: %s" % frame_idx)
#        cv2.imwrite('frame_combined_hist2_%06d.png' % frame_idx, frame)
#        prev_hit = True
#    else:
#        prev_hit = False


    print("Ret: %s\tidx: %s\ttime: %.2f\tdiff: %s\t" % (ret, frame_idx, time_idx, d_colors))
#    print("Ret: %s\tidx: %s\ttime: %.2f\tdiff: %s\t%s\t%s" % (ret, frame_idx, time_idx, d_colors, d_hist, d_hist2))
    prev_frame = frame_gray
    prev_hist = hist
    prev_d_colors = d_colors


#    if int(frame_idx) % 100 == 0:
#        cv2.imwrite('frame%06d.png' % frame_idx, frame)

#    if int(frame_idx) == 3:
#        break




print("Frames: %s/%s" % (nFrames, frame_idx))
cap.release()
