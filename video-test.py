#!/usr/bin/env python
"""Testing of video presentation slides extractor"""

import os
import sys

import cv2
import numpy as np


def get_slide_transitions(video, mask=None, trigger_ratio=5, minimum_total_change=0.06, minimum_slide_length=20,
                          motion_capture_averaging_time=10):
    """
    Gather a list of transitions from an input video.
    The algorithm leverages motion tracking techniques and works well with unprocessed screen capture (heavy compression
    can introduce false positives). A portion of the image can be masked out for cases where you may have live video
    superimposed on the frame.

    :param video: path to the video
    :param mask: the area to mask out
    :param trigger_ratio: the relative ratio of changed pixels that causes a trigger
    :param minimum_total_change: minimum number of pixels that must change to register a trigger (on a scale between 0
    to 1, with a default of 6%)
    :param minimum_slide_length: minimum length of a slide (in seconds)
    :param motion_capture_averaging_time: the time over which to build up our average of the background (in seconds)
    :param seconds_to_delay_grab: number of seconds to delay the frame grab for a trigger (useful if there are slide
    transition animations and the default 1 second delay is harmless in most cases)
    """
    cap = cv2.VideoCapture(video)

    # Grab some basic information about the video
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    # I would like to change the sampling FPS to something like 5fps since this would mean processing a lot less frames
    # but using cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index) is actually very slow and not worth the change
    fps = cap.get(cv2.CAP_PROP_FPS)  # Assuming non-variable FPS
    num_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)

    slides = []
    errors = []

    # Verify the algorithm parameters make sense:
    #
    # Check the path to the video exists
    if not os.path.exists(video):
        errors += ["Path to video does not exist!\n"]
    # Verify the mask is set for a sensible region
    if mask:
        if (mask['x2'] > width) or (mask['y2'] > height):
            errors += ["Mask is outside bounds of image!"]
    # Give some reasonable bounds for the trigger ratio
    if trigger_ratio < 2 or trigger_ratio > 10:
        errors += ["Expected a trigger ratio in range from 2 to 10!"]
    # Give some reasonable bounds for the minimum total change
    if minimum_total_change < 0 or minimum_total_change > 1:
        errors += ["Expected a minimum_total_change on a scale from 0.0 to 1.0!"]
    # Check minimum slide length is less than the length of the video
    if minimum_slide_length > fps * num_frames:
        errors += ["The video length is less than the minimum slide length!"]
    # Check the motion_capture_averaging_time makes sense
    if motion_capture_averaging_time > minimum_slide_length:
        errors += ["motion_capture_averaging_time cannot be longer than minimum_slide_length!"]

    if errors:
        return slides, errors

    # Set lower bound on our pixel change average
    min_pixel_change_av = (minimum_total_change / trigger_ratio) * \
                          ((width * height) - (mask['x2'] - mask['x1'])*(mask['y2'] - mask['y1']))

    # Set the number of frames for the minimum length of a slide
    minimum_slide_length_in_frames = int(round(minimum_slide_length * fps))

    #  Allocate space for our average of the changes of the frames in the last averaging_time seconds
    averaging_frames = int(motion_capture_averaging_time * fps)
    av_array = np.zeros(averaging_frames, dtype=int)

    # Set up the motion capture algorithm to learn over our set averaging time and output B/W images
    fgbg = cv2.createBackgroundSubtractorKNN(history=averaging_frames, detectShadows=False)

    # Set the number of frames we can safely ignore after we have a trigger,which is the minimum slide length adjusted
    # for our averaging_frames frames so that we have the correct average and bg memory
    ignore_frames = (minimum_slide_length * fps) - averaging_frames

    frame_index = 0
    previous_trigger_frame = 0
    average = 0.0
    percent_processed = 0
    print "Starting analysis:"
    while frame_index < num_frames:
        _, frame = cap.read()

        # Apply our mask
        if mask:
            frame[mask['y1']:mask['y2'], mask['x1']:mask['x2'], 0:3] = 0

        # Check to we are in the region where a slide will never be extracted (due to min_slide_length). If so, don't do
        # any of the hard work.

        if frame_index > (previous_trigger_frame + ignore_frames) or frame_index == 0:
            # Apply the mask and count the white pixels
            fgmask = fgbg.apply(frame)
            # If you want to see what the algorithm is looking at, uncomment the below
            # cv2.imshow('frame', fgmask)
            # if cv2.waitKey(1) & 0xFF == ord('q'):
            # break

            # Count the changed pixels (based on the learned background)
            whites = int(cv2.countNonZero(fgmask))

            # Check if we have a trigger
            if (frame_index - previous_trigger_frame) > minimum_slide_length_in_frames or frame_index == 0:
                if average > min_pixel_change_av:
                    proxy_average = average
                else:
                    proxy_average = min_pixel_change_av

                if (whites > trigger_ratio * proxy_average) or frame_index == 0:
                    # Grab the slide
                    timestamp = cap.get(cv2.CAP_PROP_POS_MSEC)
                    slides += [{"frame_index": frame_index, "timestamp": timestamp}]

                    previous_trigger_frame = frame_index
                    # Restart the averaging process
                    average = 0.0
                    av_array[:] = 0

            # Update our average and the associated array. Since we know that the average is restarted after every
            # trigger things are sequential and it is safe to use modulo here.
            if previous_trigger_frame != frame_index:
                # First remove the value of the previous entry from the average
                average -= av_array[frame_index % averaging_frames] / float(averaging_frames)
                # Add the new value to the array
                av_array[frame_index % averaging_frames] = whites
                # Update the average
                average += av_array[frame_index % averaging_frames] / float(averaging_frames)

        # Let people know how far along we are
        frame_index += 1
        if (frame_index % round(num_frames/100.0)) == 0:
            percent_processed += 1
            print "Processed {:3d}%".format(percent_processed)

    return slides, errors

def save_screenshots(video, slides, path_to_save, seconds_to_delay_screenshot=1):
    cap = cv2.VideoCapture(video)
    for slide in slides:
        # Set the time position of the slide for the grab
        cap.set(cv2.CAP_PROP_POS_MSEC, slide["timestamp"] + seconds_to_delay_screenshot*1000)
        # Grab the image
        _, frame = cap.read()
        # Save the image
        cv2.imwrite(os.path.join(path_to_save, 'frame_index-' + str(slide['frame_index']) + '.png'), frame)


# Take the video from the command line
video = sys.argv[1]
# Assume an HD1080 image with a superimposed video in the bottom right corner
mask = {
    "x1": 1600,
    "y1": 845,
    "x2": 1920,
    "y2": 1080,
}
slides, errors = get_slide_transitions(video, mask=mask)
errors = []
if errors:
    print errors
    exit()

for slide in slides:
    print round(slide['timestamp']/1000)

print slides
save_screenshots(video, slides, './', seconds_to_delay_screenshot=0)
