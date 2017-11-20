This is a previewer for the video recording of a presentation. It will use the metadata from the
video-presentation extractor to create bookmarks at the different slides. The actual previewer uses
[Video.js](http://videojs.com) to show the video along with the [Chapter Thumbnails plugin](http://github.com/chemoish/videojs-chapter-thumbnails).

The WebVTT needed for the chapters is generated on the fly using the JSON-LD metadata from the extractor.


# Installation

You need to put this directory under the `custom/public/javascripts/previewers/` directory of Clowder. It should
be picked up automatically by Clowder. Furthermore you need to add the `video/slidespresentation` type to the 
`mimetypes.conf` file:

```
mimetype.slidespresentation=video/slidespresentation
mimetype.SLIDESPRESENTATION=video/slidespresentation
```
