#!/usr/bin/env python
"""
Slides extractor from a video

Author Ward Poelmans <wpoely86@gmail.com>
"""

import datetime
import json
import logging
import os
import shutil
import tempfile

import cv2  # OpenCV
import numpy as np

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
# x1..x2 and y1..y2 is mask out in the frame. In this example, it"s a box in the top right.
# Alternativily, you can also pass percentages:
# {
#    "x1": "5%",
#    "y1": "10%",
#    "x2": "2%",
#    "y2": "7%",
# }
# Which will be converted to the previous form based on the frame resolution. If you leave
# out x2 and y2, it will be assumed they are 100%

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

        self.results = None
        self.tempdir = None
        self.masksettings = None
        self.read_mask_settings()

    def read_mask_settings(self, filename=None):
        """
        Read the default settings for masking from the give file.
        :param filename: optional path to settings file (defaults to 'settings.json' in the current directory)
        """
        if filename is None:
            filename = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config", "settings.json")

        if not os.path.isfile(filename):
            self.logger.warning("No config file found at %s", filename)
            return

        try:
            with open(filename, 'r') as settingsfile:
                settings = json.load(settingsfile)
                self.masksettings = settings['masks']
        except (IOError, ValueError, KeyError) as err:
            self.logger.error("Failed to read or parse %s as settings file: %s", filename, err)

        self.logger.debug("Read settings from %s", filename)

    def check_message(self, connector, host, secret_key, resource, parameters):  # pylint: disable=unused-argument,too-many-arguments
        """Check if the extractor should download the file or ignore it."""
        if not resource['file_ext'] == '.slidespresentation':
            self.logger.debug("Unknown filetype, skipping")
            return pyclowder.utils.CheckMessage.ignore

        return pyclowder.utils.CheckMessage.download  # or bypass

    def process_message(self, connector, host, secret_key, resource, parameters):  # pylint: disable=unused-argument,too-many-arguments
        """The actual extractor: we process the video and upload the results"""
        self.logger.debug("Clowder host: %s", host)
        self.logger.debug("Received resources: %s", resource)
        self.logger.debug("Received parameters: %s", parameters)

        # we reread the settings on every file we process
        self.read_mask_settings()

        usersettings = json.loads(parameters.get('parameters', '{}'))
        usermask = usersettings.get('masks')
        if isinstance(usermask, (dict, list)):
            self.masksettings = usermask

        self.tempdir = tempfile.mkdtemp(prefix='clowder-video-presentation')

        self.find_slides_transitions(connector, host, secret_key, resource, masks=self.masksettings)

        # first and last frame will always be in self.results
        if self.results and len(self.results) > 2:
            slidesmeta = {
                'nrslides': len(self.results) - 1,  # the last frame always gets added too
                'listslides': [],
            }

            # first chapter starts at.
            # Big assumption: the length of the movie is less then 24 hours
            prev_time = datetime.datetime.utcfromtimestamp(0) + datetime.timedelta(milliseconds=self.results[0][1])
            previewid = self.results[0][2]

            # the WebVTT time format needs to be 00:00:00.000
            format_str = "%H:%M:%S.%f"

            for _, time_idx, new_previewid in self.results[1:]:
                begin_delta = datetime.datetime.utcfromtimestamp(0) + datetime.timedelta(milliseconds=time_idx)
                # microseconds always get printed as 6 digits passed with zeros, so we delete the last 3 digits
                slidesmeta['listslides'].append((str(prev_time.strftime(format_str)[:-3]), str(begin_delta.strftime(format_str)[:-3]), str(previewid)))
                previewid = new_previewid
                prev_time = begin_delta

            metadata = self.get_metadata(slidesmeta, 'file', resource['id'], host)
            self.logger.debug("New metadata: %s", metadata)

            # upload metadata
            pyclowder.files.upload_metadata(connector, host, secret_key, resource['id'], metadata)

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
        axis = {
            'y1': 0,
            'y2': 0,
            'x1': 1,
            'x2': 1,
        }

        for mask in masks:
            for coord in axis.keys():
                if str(mask.get(coord, '')).endswith('%'):
                    mask[coord] = int(frame[axis[coord]] * float(mask[coord].strip('%'))/100.0)

            if 'x2' not in mask:
                mask['x2'] = int(frame[1])
            if 'y2' not in mask:
                mask['y2'] = int(frame[0])

        self.logger.debug("Masks after preparing: %s", masks)

    def find_slides_transitions(self, connector, host, secret_key, resource, masks=None):  # pylint: disable=unused-argument,too-many-arguments
        """
        Find slide transitions in a video. Currently uses one method:
            - Convert to greyscale
            - Create a diff of two consecutive frames
            - Check how many pixels have changed 'significantly'
            - If enough: new slide

        :param masks: list of area to mask out before doing slide transition detection
        :return list with tuples of frame number, timestamp and id of a preview of every found slide transition.
        """
        if masks is None:
            masks = []
        elif not isinstance(masks, list):
            masks = [masks]

        self.logger.debug("Slide transition detection started on %s", resource['local_paths'][0])
        cap = cv2.VideoCapture(resource['local_paths'][0])
        if not cap.isOpened():
            self.logger.error("Failed to open file %s", resource['local_paths'][0])
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        nFrames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.logger.debug("FPS: %d, total frames: %d", fps, nFrames)

        frame_size = (int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
        self.logger.debug("Resolution: %s", frame_size)
        prev_frame = np.zeros(frame_size, np.uint8)

        self.prepare_masks(masks, frame_size)

        self.results = []

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
                for mask in masks:
                    frame_gray[mask['y1']:mask['y2'], mask['x1']:mask['x2']] = 0
            except (KeyError, ValueError) as err:
                self.logger.error("Failed to apply mask %s: %s", mask, err)

            # Find the number of pixels that have (significantly) changed since the last frame
            frame_diff = cv2.absdiff(frame_gray, prev_frame)
            _, frame_thres = cv2.threshold(frame_diff, 115, 255, cv2.THRESH_BINARY)
            d_colors = float(np.count_nonzero(frame_thres)) / frame_gray.size

            if d_colors > 0.01:
                self.logger.debug("Found slide transition at frame %d, time: %s", frame_idx, time_real)
                slidepath = os.path.join(self.tempdir, 'slide%05d.png' % (len(self.results)+1))
                cv2.imwrite(slidepath, frame)

                # Create section for file
                sectionid = sections_upload(connector, host, secret_key, {'file_id': resource['id']})
                slidemeta = {
                    'section_id': sectionid,
                    'width': str(float(frame.shape[1])),  # this doesn't seem to work...
                    'height': str(float(frame.shape[0])),
                }
                description = "Slide %2d at %s" % (len(self.results)+1, time_real)
                # upload preview & associated it with the section
                previewid = pyclowder.files.upload_preview(connector, host, secret_key, resource['id'], slidepath, slidemeta)
                # add a description to every preview
                pyclowder.sections.upload_description(connector, host, secret_key, sectionid, {'description': description})
                self.results.append((frame_idx, time_idx, previewid))

            prev_frame = frame_gray

            if frame_idx % (10*fps) == 0:
                self.logger.debug("Slide transition detection %.2f%% done\t%s", float(frame_idx)/nFrames*100, time_real)


        self.results.append((frame_idx, time_idx, None))
        cap.release()


if __name__ == "__main__":
    extractor = VideoMetaData()
    extractor.start()
