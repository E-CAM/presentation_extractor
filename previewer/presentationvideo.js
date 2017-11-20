(function ($, Configuration) {
    console.log("Video presentation previewer for " + Configuration.id);

    var useTab = Configuration.tab;
    var referenceUrl = Configuration.url;
    var confId = Configuration.id;
    var fileId = Configuration.fileid;

    // loading Video.js + plugins
    // we start with the stylesheets
    var s = document.createElement("link");
    s.rel = "stylesheet";
    s.type = "text/css";
    s.href =  Configuration.previewer + "/video-js.css";
    $(useTab).append(s);

    s = document.createElement("link");
    s.rel = "stylesheet";
    s.type = "text/css";
    s.href = Configuration.previewer + "/videojs-chapter-thumbnails/videojs.chapter-thumbnails.min.css";
    $(useTab).append(s);

    $(useTab).append("<br/>");

    // load Video.js
    var videojs_req = $.ajax({
        url: Configuration.previewer + "/video.js",
        dataType: "script",
        context: this,
    });

    // load the JSON-LD from the extractor (needed for the WebVTT)
    var extractor_req = $.ajax({
        type: "GET",
        url: jsRoutes.api.Files.getMetadataJsonLD(fileId, "ncsa.videopresentation/1.0").url,
        dataType: "json"
    });

    // only load the plugin after Video.js itself has been loaded.
    var videojs_thumb_plugin = $.when(videojs_req).then(function() {
        return $.ajax({
            url: Configuration.previewer + "/videojs-chapter-thumbnails/videojs.chapter-thumbnails.min.js",
            dataType: "script",
            context: this,
        });
    });

    // when both the plugins and the JSON-LD are loaded, we can show the previewer
    $.when(extractor_req, videojs_thumb_plugin).done(function(extract_data, videojs_plugin){
        console.log("Creating the video presentation previewer");
        console.log(extract_data);

        // create the WebVTT file: first the mandatory header
        var vtt_list = ["WEBVTT", ""]

        try {
            extract_data[0][0]['content']['listslides'].forEach(function(elem, index){
                vtt_list.push("Slide " + (index+1));
                vtt_list.push(elem[0] + " --> " + elem[1]);
                vtt_list.push('{"title":"Slide ' + (index+1) + '", "image": "'+ jsRoutes.api.Previews.download(elem[2]).url +'"}');
                vtt_list.push("");
            });
        } catch(err) {
            console.log("Failed to create the WebVTT: " + err.message);
        }

        var webvtt = vtt_list.join('\n');
        console.log(webvtt);


        // Showing the original file. 
        // This also means the "preview" is a single video and not a multi-option cross-browser compatibility combination,
        // as those can only be generated as previews by the system. 
        // Thus, show the file as a single video.
        if(confId == fileId){
            $(useTab).append(
                "<video id='mypresentationvideo' class='video-js vjs-fluid vjs-default-skin' controls preload='auto' data-setup='{}'>" +
                "<source src='" + referenceUrl + "' type='video/mp4'>" +
//                "<track kind='chapters' src='data:text/plain;base64,"+ window.btoa(webvtt) +"' default>" +
                "<p class='vjs-no-js'>" +
                "To view this video consider upgrading to a web browser that " +
                "<a href='http://videojs.com/html5-video-support/' target='_blank'>supports HTML5 video.</a></p>" +
                "</video>"
            );

            // initialize the video element just added + plugin
            videojs('mypresentationvideo').chapter_thumbnails({
                src: 'data:text/plain;base64,' + window.btoa(webvtt),
            });
        }

    }).fail(function(err){
        console.log("Failed to load all scripts for video presentation previewer: " + err['status'] + " - " + err['statusText']);
    });
    
}(jQuery, Configuration));
