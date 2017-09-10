#!/usr/bin/env python
"""
Slides extractor from a video

Author Ward Poelmans <wpoely86@gmail.com>
"""

import datetime
import logging
# import subprocess

import cv2
import numpy as np

from pyclowder.extractors import Extractor
import pyclowder.files
from pyclowder.utils import CheckMessage

tomask = {
    'x': 1018,
    'y': 0,
    'b': 342,
    'h': 194,
}
tomask['x2'] = tomask['x'] + tomask['b']
tomask['y2'] = tomask['y'] + tomask['h']


class VideoMetaData(Extractor):
    """Extract slide transitions in a video"""
    def __init__(self):
        Extractor.__init__(self)

        # parse command line and load default logging configuration
        self.setup()

        # setup logging for the exctractor
        logging.getLogger('pyclowder').setLevel(logging.DEBUG)
        logging.getLogger('__main__').setLevel(logging.DEBUG)

        self.results = None

    def check_message(self, connector, host, secret_key, resource, parameters):  # pylint: disable=unused-argument,too-many-arguments
        """The extractor to not download the file."""
        logger = logging.getLogger(__name__)
        if not resource['file_ext'] == '.mp4':
            logger.debug("Unknown filetype, skipping")
            return CheckMessage.ignore

        return CheckMessage.download  # or bypass

    def process_message(self, connector, host, secret_key, resource, parameters):  # pylint: disable=unused-argument,too-many-arguments
        """The actual extractor"""
        # Process the file and upload the results

# resources: {'intermediate_id': u'59b3fe55e4b03bcb8e8bf30f', 'parent': {'type': 'dataset', 'id': u'598a233be4b03bcb4644e284'}, 'local_paths': [u'/tmp/tmpgpaHdP.mp4'], 'file_ext': u'.mp4', 'type': 'file', 'id': u'59b3fe55e4b03bcb8e8bf30f', 'name': u'zoom.mp4'}

# parameters: {u'parameters': u'{}', 'routing_key': 'extractors.ncsa.videopresentation', u'filename': u'zoom.mp4', u'secretKey': u'r1ek3rs', u'host': u'http://clowder:9000', u'flags': u'', u'fileSize': u'87656172', u'intermediateId': u'59b3fe55e4b03bcb8e8bf30f', u'action': u'manual-submission', u'id': u'59b3fe55e4b03bcb8e8bf30f', u'datasetId': u'598a233be4b03bcb4644e284'}

        logger = logging.getLogger(__name__)
        logger.debug("Got host: %s", host)
        logger.debug("Got resources: %s", resource)
        logger.debug("Got parameters: %s", parameters)

        self.find_slides_transitions(connector, host, secret_key, resource, parameters, masks=tomask)

        if self.results and len(self.results) > 1:
            slidesmeta = {
                'nrslides': len(self.results),
                'listslides': [],
            }
            for _, time in self.results:
                slidesmeta['listslides'].append(str(datetime.timedelta(milliseconds=time)))
            metadata = self.get_metadata(slidesmeta, 'file', resource['id'], host)
            logger.debug(metadata)

            # upload metadata
            pyclowder.files.upload_metadata(connector, host, secret_key, resource['id'], metadata)



    def find_slides_transitions(self, connector, host, secret_key, resource, parameters, masks=None):  # pylint: disable=unused-argument,too-many-arguments
        """
        Find slide transitions in a video. Currently uses one method:
            - Convert to greyscale
            - Create a diff of two consecutive frames
            - Check how many pixels have changed 'significantly'
            - If enough: new slide

        :param masks: list of area to mask out before doing slide transition detection
        :return list with tuples of frame number and timestamp of every found slide transition.
        """
        logger = logging.getLogger(__name__)

        if masks is None:
            masks = []
        if not isinstance(masks, list):
            masks = [masks]

        logger.debug("Slide transition detection started on %s", resource['local_paths'][0])
        cap = cv2.VideoCapture(resource['local_paths'][0])
        if not cap.isOpened():
            logger.error("Failed to open file %s", resource['local_paths'][0])
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        nFrames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        logger.debug("FPS: %d, total frames: %d", fps, nFrames)

        # Do first frame outside loop
        ret, frame = cap.read()
        logger.debug("Resolution: %s", frame.shape)

        for mask in masks:
            frame[mask['y']:mask['y2'], mask['x']:mask['x2']] = [0, 0, 0]
        prev_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        self.results = [(0, 0.0)]

        # Start processing from the second frame
        while True:
            frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            time_idx = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            ret, frame = cap.read()
            if not ret:
                break

            for mask in masks:
                frame[mask['y']:mask['y2'], mask['x']:mask['x2']] = [0, 0, 0]

            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # METHOD #1: find the number of pixels that have (significantly) changed since the last frame
            frame_diff = cv2.absdiff(frame_gray, prev_frame)
            _, frame_thres = cv2.threshold(frame_diff, 115, 255, cv2.THRESH_BINARY)
            d_colors = float(np.count_nonzero(frame_thres)) / frame_gray.size

            if d_colors > 0.01:
                logger.debug("Found slide transition at frame %d, time: %s", frame_idx, datetime.timedelta(milliseconds=time_idx))
                self.results.append((frame_idx, time_idx))

            prev_frame = frame_gray

            if frame_idx % (10*fps) == 0:
                logger.debug("%.2f done\t%s", float(frame_idx)/nFrames*100, time_idx)

        cap.release()


if __name__ == "__main__":
    extractor = VideoMetaData()
    extractor.start()
