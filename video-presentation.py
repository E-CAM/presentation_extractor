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

default_settings_basic = {
    'threshold_cutoff' : 115,
    'trigger' : 0.01,
}

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
                settings = yaml.safe_load(settingsfile)
                self.masksettings = settings.get('masks', [])
                algorithmsettings = settings.get('slides')
                self.algorithmsettings = algorithmsettings[0] if algorithmsettings else {}
        except (IOError, yaml.YAMLError) as err:
            self.logger.error("Failed to read or parse %s as settings file: %s", filename, err)

        self.logger.debug("Read settings from %s: %s + %s", filename, self.masksettings, self.algorithmsettings)

    def check_message(self, connector, host, secret_key, resource, parameters):  # pylint: disable=unused-argument,too-many-arguments
        """Check if the extractor should download the file or ignore it."""
        if not resource['file_ext'] == '.slidespresentation':
            if parameters.get('action', '') != 'manual-submission':
                self.logger.debug("Unknown filetype, skipping")
                return pyclowder.utils.CheckMessage.ignore
            else:
                self.logger.debug("Unknown filetype, but scanning by manuel request")

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

        if self.algorithmsettings.get('algorithm', '') == "basic":
            settings = dict(default_settings_basic)  # make sure it's a copy
            settings.update(self.algorithmsettings)
            del settings['algorithm']  # not an argument for the method
            self.logger.debug("Using basic algorithm for finding slides. settings: %s", settings)
            results = self.slide_find_basic(resource['local_paths'][0], masks=masks, **settings)
        else:
            settings = dict(default_settings_advanced)  # make sure it's a copy
            settings.update(self.algorithmsettings)
            del settings['algorithm']  # not an argument for the method
            self.logger.debug("Using advanced algorithm for finding slides. settings: %s", settings)
            results = self.slide_find_advanced(resource['local_paths'][0], masks=masks, **settings)

        self.results = []

        slidesmeta = {
            'nrslides': 0,
            'listslides': [],
            'algorithm': self.algorithmsettings.get('algorithm', 'advanced'),
            'settings': settings,
        }
        self.logger.debug("tmp results: %s", results)

        for idx, (frame_idx, time_idx, slidepath) in enumerate(results):
            # last second/frame always gets added for WebVTT but hasn't got a slidepath set
            if not slidepath:
                self.results.append((frame_idx, time_idx, None))
                continue

            # Create section for file
            sectionid = sections_upload(connector, host, secret_key, {'file_id': resource['id']})
            slidemeta = {
                'section_id': sectionid,
            }
            description = "Slide %2d at %s" % (idx + 1, datetime.timedelta(milliseconds=time_idx))
            # upload preview & associated it with the section
            previewid = pyclowder.files.upload_preview(connector, host, secret_key, resource['id'], slidepath, slidemeta)
            # add a description to every preview
            pyclowder.sections.upload_description(connector, host, secret_key, sectionid, {'description': description})

            self.results.append((frame_idx, time_idx, previewid))

        self.logger.debug("final results: %s", self.results)

        # first and last frame will always be in self.results
        if self.results and len(self.results) > 1:
            slidesmeta['nrslides'] = len(self.results) - 1,  # the last frame always gets added too

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

    def slide_find_advanced(self, filename, masks=None, trigger_ratio=5, minimum_total_change=0.06, minimum_slide_length=20,
                            motion_capture_averaging_time=10):
        """coming"""


    def slide_find_basic(self, filename, masks=None, threshold_cutoff=115, trigger=0.01):  # pylint: disable=too-many-locals
        """
        Find slide transitions in a video. Method:
            - Convert to greyscale
            - Create a diff of two consecutive frames
            - Check how many pixels have changed 'significantly'
            - If enough: new slide

        :param masks: list of area to mask out before doing slide transition detection
        :return list with tuples of frame number, timestamp and path to screenshot of slide
        """
        if masks is None:
            masks = []
        elif not isinstance(masks, list):
            masks = [masks]

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
