#!/usr/bin/env python
"""
Slides extractor from a video

Author Ward Poelmans <wpoely86@gmail.com>
"""

import datetime
import json
import logging
import multiprocessing
import os
import shutil
import subprocess
import tempfile

import cv2  # OpenCV
import numpy as np
import yaml

import pyclowder
from pyclowder.extractors import Extractor
from pyclowder.sections import upload as sections_upload

# For the mask settings, for example:
#
# {
#    "x1": 1108,
#    "y1": 589,
#    "x2": 1280,
#    "y2": 720,
# }
#
# x1..x2 and y1..y2 is mask out in the frame. In this example, it"s a box in the top right. However, 
# there is an alternative format which is easier to use (will be converted to the above one internally):
#
# {
#     "masks": [
#     {
#         "location": "top-right",
#         "size_x": 300,
#         "size_y": 300
#     },
#     {
#         "location": "bottom-left",
#         "size_x": "1%",
#         "size_y": "2%"
#     }]
# }


# Comments for DASH:
#
# -profile:v main should not be needed?
# command = "ffmpeg -i %(inputfile)s -f dash -vf 'scale=-1:240' -c:v libx264 -x264opts \
# 'keyint=%(rate)s:min-keyint=%(rate)s:no-scenecut' -crf 23 -preset medium -movflags +faststart \
# -c:a copy %(outputfile)s"
#
# Assuming 16:9
# 256  x 144
# 512  x 288
# 640  x 360
# 800  x 450
# 960  x 540
# 1024 x 576
# 1152 x 648
# 1280 x 720
# 1920 x 1080
#
# References:
# - https://superuser.com/questions/908280/what-is-the-correct-way-to-fix-keyframes-in-ffmpeg-for-dash
# - https://blog.streamroot.io/encode-multi-bitrate-videos-mpeg-dash-mse-based-media-players/
# - https://trac.ffmpeg.org/wiki/Encode/H.264

default_settings_advanced = {
    'trigger_ratio' : 5,
    'minimum_total_change' : 0.06,
    'minimum_slide_length' : 20,
    'motion_capture_averaging_time' : 10,
    'msec_to_delay_screenshot' : 1000,
}

default_settings_basic = {
    'threshold_cutoff' : 115,
    'trigger' : 0.01,
}

# Add function to do compression that is pickle-able
def create_video_previews(filename, output_dir, mp4_filename, webm_filename):
    """Create mp4 and webm heavily compressed previews of the presentation to use in the previewer"""

    # Let's not be greedy, use half available cores since we are probably in a docker container
    # This could be done less crudely, we could leave this control to the container
    encoding_threads = multiprocessing.cpu_count()
    if encoding_threads > 1:
        encoding_threads = int(np.ceil(encoding_threads / 2))

    ffmpeg_stub = "ffmpeg -loglevel error -y -i \"" + os.path.abspath(filename) + "\" -threads " + \
                  str(encoding_threads)
    # We use the same audio settings for both videos
    no_audio = " -an "
    mp4_audio = " -strict -2 -acodec aac -ac 1 -b:a 64k "
    webm_audio = " -acodec libopus -ac 1 -b:a 64k "
    # Use very heavy compression since most of what we deal with is 2d without shadows
    mp4_settings = " -vcodec libx264 -preset medium -b:v 96k -qmax 42 -maxrate 250k "
    webm_settings = " -vcodec libvpx -quality good -b:v 96k -crf 10 -qmin 0 -qmax 42 -maxrate 250k -bufsize 1000k "

    # The 2 pass method requires some temporary files so let's (temporarily) change to the output dir we have
    currentdir = os.getcwd()
    os.chdir(output_dir)

    # First let's do mp4
    ffmpeg_command = ffmpeg_stub + mp4_settings + no_audio + "-pass 1 -f mp4 /dev/null"
    # using the shell is a potential security hazard but our filenames are sanitized by Clowder
    subprocess.check_output(ffmpeg_command, stderr=subprocess.STDOUT, shell=True)
    ffmpeg_command = ffmpeg_stub + mp4_settings + mp4_audio + "-pass 2 -f mp4 " + mp4_filename
    subprocess.check_output(ffmpeg_command, stderr=subprocess.STDOUT, shell=True)
    # Now do webm
    ffmpeg_command = ffmpeg_stub + webm_settings + no_audio + "-pass 1 -f webm /dev/null"
    subprocess.check_output(ffmpeg_command, stderr=subprocess.STDOUT, shell=True)
    ffmpeg_command = ffmpeg_stub + webm_settings + webm_audio + "-pass 2 -f webm " + webm_filename
    subprocess.check_output(ffmpeg_command, stderr=subprocess.STDOUT, shell=True)

    # Change back to the original directory
    os.chdir(currentdir)

    return

class VideoMetaData(Extractor):
    """Extract slide transitions in a video"""
    def __init__(self):
        Extractor.__init__(self)

        # parse command line and load default logging configuration
        self.setup()

        # setup logging for the exctractor
        logging.getLogger('pyclowder').setLevel(logging.DEBUG)
        logging.getLogger('__main__').setLevel(logging.DEBUG)
        self.logger = logging.getLogger(__name__)

        self.results = []
        self.tempdir = None
        self.masksettings = None
        self.algorithmsettings = None
        self.read_settings()

    def read_settings(self, filename=None):
        """
        Read the default settings for the extractor from the given file.
        :param filename: optional path to settings file (defaults to 'settings.yml' in the current directory)
        """
        if filename is None:
            filename = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config", "settings.yml")

        if not os.path.isfile(filename):
            self.logger.warning("No config file found at %s", filename)
            return

        try:
            with open(filename, 'r') as settingsfile:
                settings = yaml.safe_load(settingsfile) or {}
                self.masksettings = settings.get('masks', [])
                algorithmsettings = settings.get('slides')
                self.algorithmsettings = algorithmsettings[0] if algorithmsettings else {}
        except (IOError, yaml.YAMLError) as err:
            self.logger.error("Failed to read or parse %s as settings file: %s", filename, err)

        self.logger.debug("Read settings from %s: %s + %s", filename, self.masksettings, self.algorithmsettings)

    def check_message(self, connector, host, secret_key, resource, parameters):  # pylint: disable=unused-argument,too-many-arguments
        """Check if the extractor should download the file or ignore it."""
        if not resource['file_ext'] == '.mp4' and not resource['file_ext'] == '.webm':
            if parameters.get('action', '') != 'manual-submission':
                self.logger.debug("Unknown filetype %s (default support is for mp4/webm, other filestypes must be manually submitted), skipping", resource['file_ext'])
                return pyclowder.utils.CheckMessage.ignore
            else:
                self.logger.debug("Unknown filetype, but scanning by manual request")

        return pyclowder.utils.CheckMessage.download  # or bypass

    def process_message(self, connector, host, secret_key, resource, parameters):  # pylint: disable=unused-argument,too-many-arguments
        """The actual extractor: we process the video and upload the results"""
        self.logger.debug("Clowder host: %s", host)
        self.logger.debug("Received resources: %s", resource)
        self.logger.debug("Received parameters: %s", parameters)

        # we reread the settings on every file we process
        self.read_settings()

        usersettings = json.loads(parameters.get('parameters', '{}'))
        usermask = usersettings.get('masks')
        if isinstance(usermask, (dict, list)):
            self.masksettings = usermask

        userslides = usersettings.get('slides')
        if isinstance(userslides, dict):
            self.algorithmsettings.update(userslides)

        self.tempdir = tempfile.mkdtemp(prefix='clowder-video-presentation')

        self.find_slides_transitions(connector, host, secret_key, resource, masks=self.masksettings)

        shutil.rmtree(self.tempdir, ignore_errors=True)

    def generate_vtt_chapters(self):
        """Generate a WebVTT that defines the chapters"""
        # first the mandatory WebVTT header
        vttfile = ["WEBVTT", ""]

        # first chapter starts at.
        # Big assumption: the length of the movie less then 24 hours
        prev_time = datetime.datetime.utcfromtimestamp(0) + datetime.timedelta(milliseconds=self.results[0][1])

        # the format needs to be 00:00:00.000
        format_str = "%H:%M:%S.%f"

        # continue from the second slide
        for idx, (_, time_idx) in enumerate(self.results[1:]):
            begin_delta = datetime.datetime.utcfromtimestamp(0) + datetime.timedelta(milliseconds=time_idx)
            # microseconds always get printed as 6 digits passed with zeros, so we delete the last 3 digits
            vttfile.append("%s --> %s" % (prev_time.strftime(format_str)[:-3], begin_delta.strftime(format_str)[:-3]))
            vttfile.append("Slide %d" % (idx+1))
            vttfile.append("")
            prev_time = begin_delta

        return vttfile

    def prepare_masks(self, masks, frame):
        """
        Convert masks to 'proper' masks: x1..x2 and y1..y2
        :param masks: the list of areas to mask out
        :param frame: tuple contain the resolution of the video
        """
        locations_hori = ['right', 'left']
        locations_vert = ['top', 'bottom']

        def parsevalue(size, max_size):
            """handle % values"""
            if str(size).endswith('%'):
                return int(max_size * float(size.strip('%'))/100.0)

            return int(size)

        parsed_masks = []
        for mask in masks:
            where = mask.get('location', '').split('-')
            if len(where) != 2 or where[0] not in locations_vert or where[1] not in locations_hori:
                self.logger.error("Invalid location setting: %s. Possible choices: %s", mask.get('location'),
                                  ', '.join(["%s-%s" % (y, x) for x in locations_hori for y in locations_vert]))
                continue

            if where[0] == "bottom":
                y2 = frame[0]
                y1 = frame[0] - parsevalue(mask.get('size_y', 0), frame[0])
            else:
                y1 = 0
                y2 = parsevalue(mask.get('size_y', 0), frame[0])

            if where[1] == "right":
                x2 = frame[1]
                x1 = frame[1] - parsevalue(mask.get('size_x', 0), frame[1])
            else:
                x1 = 0
                x2 = parsevalue(mask.get('size_x', 0), frame[1])

            parsed_masks.append({
                'x1': x1,
                'x2': x2,
                'y1': y1,
                'y2': y2,
            })

        self.logger.debug("Masks after preparing: %s", parsed_masks)
        return parsed_masks

    def find_slides_transitions(self, connector, host, secret_key, resource, masks=None):  # pylint: disable=unused-argument,too-many-arguments
        """find slides"""

        # First let's set the encoders off in the background to create our previews (uses only half available
        # processors so should be safe to leave in the background)
        mp4_preview = "preview.mp4.preview"
        webm_preview = "preview.webm.preview"
        encode_job = multiprocessing.Process(target=create_video_previews,
                                             args=(resource['local_paths'][0], self.tempdir, mp4_preview, webm_preview))
        encode_job.start()

        if self.algorithmsettings.get('algorithm', '') == "basic":
            settings = dict(default_settings_basic)  # make sure it's a copy
            settings.update(dict([(a, b) for a, b in self.algorithmsettings.iteritems()
                                  if a in default_settings_basic.keys()]))
            self.logger.debug("Using basic algorithm for finding slides. settings: %s", settings)
            results = self.slide_find_basic(resource['local_paths'][0], masks=masks, **settings)
        else:
            settings = dict(default_settings_advanced)  # make sure it's a copy
            settings.update(dict([(a, b) for a, b in self.algorithmsettings.iteritems()
                                  if a in default_settings_advanced.keys()]))
            self.logger.debug("Using advanced algorithm for finding slides. settings: %s", settings)
            results = self.slide_find_advanced(resource['local_paths'][0], masks=masks, **settings)

        # Wait for encoder job to finish and upload the compressed previews
        encode_job.join()
        # Check the output files exist, if so upload them
        mp4_preview_file = os.path.join(self.tempdir, mp4_preview)
        webm_preview_file = os.path.join(self.tempdir, webm_preview)
        if os.path.exists(mp4_preview_file) and os.path.exists(webm_preview_file):
            mp4_preview_id = pyclowder.files.upload_preview(connector, host, secret_key, resource['id'],
                                                            mp4_preview_file, {})
            webm_preview_id = pyclowder.files.upload_preview(connector, host, secret_key, resource['id'],
                                                             webm_preview_file, {})
        else:
            self.logger.error("Video preview files were not created correctly!")
            return []

        self.results = []

        slidesmeta = {
            'nrslides': 0,
            'listslides': [],
            'algorithm': self.algorithmsettings.get('algorithm', 'advanced'),
            'settings': settings,
            'previews': {'mp4': mp4_preview_id, 'webm': webm_preview_id},
        }
        self.logger.debug("tmp results: %s", results)

        for idx, (frame_idx, time_idx, slidepath) in enumerate(results):
            # last second/frame always gets added for WebVTT but hasn't got a slidepath set
            if not slidepath:
                self.results.append((frame_idx, time_idx, None))
                continue

            # Create section for file (currently not used)
            #sectionid = sections_upload(connector, host, secret_key, {'file_id': resource['id']})
            #slidemeta = {
            #    'section_id': sectionid,
            #}
            #description = "Slide %2d at %s" % (idx + 1, datetime.timedelta(milliseconds=time_idx))
            # upload preview & associated it with the section
            if idx == 0:
                pyclowder.files.upload_thumbnail(connector, host, secret_key, resource['id'], slidepath)
            previewid = pyclowder.files.upload_preview(connector, host, secret_key, resource['id'], slidepath, {})
            # add a description to every preview
            #pyclowder.sections.upload_description(connector, host, secret_key, sectionid, {'description': description})

            self.results.append((frame_idx, time_idx, previewid))

        self.logger.debug("final results: %s", self.results)

        # first and last frame will always be in self.results
        if self.results and len(self.results) > 1:
            slidesmeta['nrslides'] = len(self.results) - 1,  # the last frame always gets added too

            # first chapter starts at.
            # Big assumption: the length of the movie is less then 24 hours
            prev_time = datetime.datetime.utcfromtimestamp(0) + datetime.timedelta(milliseconds=self.results[0][1])
            prev_time_msec = self.results[0][1]
            previewid = self.results[0][2]

            # the WebVTT time format needs to be 00:00:00.000
            format_str = "%H:%M:%S.%f"

            for _, time_idx, new_previewid in self.results[1:]:
                begin_delta = datetime.datetime.utcfromtimestamp(0) + datetime.timedelta(milliseconds=time_idx)
                # microseconds always get printed as 6 digits passed with zeros, so we delete the last 3 digits
                slidesmeta['listslides'].append((str(prev_time.strftime(format_str)[:-3]), str(begin_delta.strftime(format_str)[:-3]), str(previewid), str(prev_time_msec / 1000)))
                previewid = new_previewid
                prev_time = begin_delta
                prev_time_msec = time_idx

        metadata = self.get_metadata(slidesmeta, 'file', resource['id'], host)
        self.logger.debug("New metadata: %s", metadata)

        # upload metadata
        pyclowder.files.upload_metadata(connector, host, secret_key, resource['id'], metadata)

    def slide_find_advanced(self, filename, **kwargs):
        """
        Gather a list of transitions from an input video.
        The algorithm leverages motion tracking techniques and works well with unprocessed screen capture (heavy compression
        can introduce false positives). A portion of the image can be masked out for cases where you may have live video
        superimposed on the frame.

        :param filename: path to the video
        :param masks: list of area to mask out before doing slide transition detection
        :param trigger_ratio: the relative ratio of changed pixels that causes a trigger
        :param minimum_total_change: minimum number of pixels that must change to register a trigger (on a scale between 0
        to 1, with a default of 6%)
        :param minimum_slide_length: minimum length of a slide (in seconds)
        :param motion_capture_averaging_time: the time over which to build up our average of the background (in seconds)
        :param msec_to_delay_screenshot: The amount of delay before taking a screenshot (good for animated slide
        transitions) in milliseconds
        :return list with tuples of frame number, timestamp and path to screenshot of slide
        """
        options = dict(default_settings_advanced)
        options.update(kwargs)

        masks = options.get('masks', [])
        if not isinstance(masks, list):
            masks = [masks]

        trigger_ratio = options.get('trigger_ratio')
        minimum_total_change = options.get('minimum_total_change')
        minimum_slide_length = options.get('minimum_slide_length')
        motion_capture_averaging_time = options.get('motion_capture_averaging_time')
        msec_to_delay_screenshot = options.get('msec_to_delay_screenshot')

        cap = cv2.VideoCapture(filename)
        if not cap.isOpened():
            self.logger.error("Failed to open file %s", filename)
            return []

        # Grab some basic information about the video
        width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        # I would like to change the sampling FPS to something like 5fps since this would mean processing a lot less frames
        # but using cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index) is actually very slow and not worth the change
        fps = cap.get(cv2.CAP_PROP_FPS)  # Assuming non-variable FPS
        num_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)

        slides = []
        errors = []

        cur_masks = self.prepare_masks(masks, (int(height), int(width)))

        # Verify the algorithm parameters make sense:
        #
        # Verify the mask is set for a sensible region
        for mask in cur_masks:
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
            for error in errors:
                self.logger.error("Algorithm parameter error: %s", error)
            return []

        # Set lower bound on our pixel change average
        mask_area = 0
        for mask in cur_masks:
            mask_area += (mask['x2'] - mask['x1']) * (mask['y2'] - mask['y1'])

        min_pixel_change_av = (minimum_total_change / trigger_ratio) * \
                              ((width * height) - mask_area)

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
        while frame_index < num_frames:
            ret, frame = cap.read()

            if not ret:
                break

            orig_frame = np.copy(frame)

            # Apply our mask
            try:
                for mask in cur_masks:
                    frame[mask['y1']:mask['y2'], mask['x1']:mask['x2'], 0:3] = 0
            except (KeyError, ValueError) as err:
                self.logger.error("Failed to apply mask %s: %s", mask, err)

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
                        self.logger.debug("Found slide transition at %s", timestamp)

                        # Set the path now, but write the image later
                        slidepath = os.path.join(self.tempdir, 'slide%05d.png' % (len(slides)+1))

                        slides.append((frame_index, timestamp, slidepath))

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
                self.logger.debug("Processed at %3d %%", percent_processed)

        # Now that we know all the transitions, grab the slide image with a configurable offset
        final_timestamp = cap.get(cv2.CAP_PROP_POS_MSEC)
        for slide in slides:
            # Set the time position of the slide for the grab
            cap.set(cv2.CAP_PROP_POS_MSEC, slide[1] + msec_to_delay_screenshot)
            # Grab the image
            _, frame = cap.read()
            # Save the image
            cv2.imwrite(slide[2], frame, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        # Add am empty slide to hold the terminating timestamp
        slides.append((frame_index, final_timestamp, None))
        cap.release()

        return slides

    def slide_find_basic(self, filename, **kwargs):  # pylint: disable=too-many-locals
        """
        Find slide transitions in a video. Method:
            - Convert to greyscale
            - Create a diff of two consecutive frames
            - Check how many pixels have changed 'significantly'
            - If enough: new slide

        :param masks: list of area to mask out before doing slide transition detection
        :parm threshold_cutoff: threshold to mark a pixel change significant
        :param trigger: fraction of pixels that need to be changed significantly to trigger new slide
        :return list with tuples of frame number, timestamp and path to screenshot of slide
        """
        options = dict(default_settings_basic)
        options.update(kwargs)

        masks = options.get('masks', [])
        if not isinstance(masks, list):
            masks = [masks]

        threshold_cutoff = options.get('threshold_cutoff')
        trigger = options.get('trigger')

        cap = cv2.VideoCapture(filename)
        if not cap.isOpened():
            self.logger.error("Failed to open file %s", filename)
            return []

        fps = int(cap.get(cv2.CAP_PROP_FPS))  # assume it's constant and we convert to integer
        nFrames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.logger.debug("FPS: %d, total frames: %d", fps, nFrames)

        frame_size = (int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
        self.logger.debug("Resolution: %s", frame_size)
        prev_frame = np.zeros(frame_size, np.uint8)

        cur_masks = self.prepare_masks(masks, frame_size)

        results = []

        # Start processing from the first frame
        while True:
            frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            time_idx = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            time_real = datetime.timedelta(milliseconds=time_idx)

            ret, frame = cap.read()
            if not ret:
                break

            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            try:
                for mask in cur_masks:
                    frame_gray[mask['y1']:mask['y2'], mask['x1']:mask['x2']] = 0
            except (KeyError, ValueError) as err:
                self.logger.error("Failed to apply mask %s: %s", mask, err)

            # Find the number of pixels that have (significantly) changed since the last frame
            frame_diff = cv2.absdiff(frame_gray, prev_frame)
            _, frame_thres = cv2.threshold(frame_diff, threshold_cutoff, 255, cv2.THRESH_BINARY)
            d_colors = float(np.count_nonzero(frame_thres)) / frame_gray.size

            if d_colors > trigger:
                self.logger.debug("Found slide transition at frame %d, time: %s", frame_idx, time_real)
                slidepath = os.path.join(self.tempdir, 'slide%05d.png' % (len(results)+1))
                cv2.imwrite(slidepath, frame)

                results.append((frame_idx, time_idx, slidepath))

            prev_frame = frame_gray

            if frame_idx % (10*fps) == 0:
                self.logger.debug("Slide transition detection %.2f%% done\t%s", float(frame_idx)/nFrames*100, time_real)


        results.append((frame_idx, time_idx, None))
        cap.release()

        return results


if __name__ == "__main__":
    extractor = VideoMetaData()
    extractor.start()
