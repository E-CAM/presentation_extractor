(function ($, Configuration) {
    console.log("Video presentation previewer for " + Configuration.id);

    var useTab = Configuration.tab;
    var referenceUrl = Configuration.url;
    var confId = Configuration.id;
    var fileId = Configuration.fileid;

    // load the JSON-LD from the extractor (needed for the WebVTT and the slide navigation)
    var extractor_req = $.ajax({
        type: "GET",
        url: jsRoutes.api.Files.getMetadataJsonLD(fileId, "ncsa.videopresentation/1.0").url,
        // if Clowder API doesn't support above call, you can use:
        // url: "/api/files/" + confId + "/metadata.jsonld?extractor=ncsa.videopresentation/1.0",
        dataType: "json"
    });

    // Loading Video.js, the chapter plugin and our carousel for the slides

    // Let's start with the stylesheets needed
    var i, s, len, myCssFiles = [ "/video-js.css", "/videojs-chapter-thumbnails/videojs.chapter-thumbnails.min.css", "/slick/slick.css", "/slick/slick-theme.css", "/slickconf.css" ];
    for (len = myCssFiles.length, i=0; i<len; ++i) {
        s = document.createElement("link");
        s.rel = "stylesheet";
        s.type = "text/css";
        s.href =  Configuration.previewer + myCssFiles[i];
        $(useTab).append(s);
    }
    $(useTab).append("<br/>");

    // load Video.js
    var videojs_req = $.ajax({
        url: Configuration.previewer + "/video.js",
        dataType: "script",
        context: this,
    });

    // only load the plugin after Video.js itself has been loaded.
    var videojs_thumb_plugin = $.when(videojs_req).then(function() {
        return $.ajax({
            url: Configuration.previewer + "/videojs-chapter-thumbnails/videojs.chapter-thumbnails.min.js",
            dataType: "script",
            context: this,
        });
    });

    // load slick to handle navigation
    // load slick.js
    var slickjs_req = $.ajax({
        url: Configuration.previewer + "/slick/slick.min.js",
        dataType: "script",
        context: this,
    });
    // load the configuration
    var slickconf_req = $.when(slickjs_req).then(function() {
        return $.ajax({
            url: Configuration.previewer + "/slickconf.js",
            dataType: "script",
            context: this,
        });
    });

    // when all the plugins and the JSON-LD are loaded, we can show the previewer
    $.when(extractor_req, videojs_thumb_plugin, slickconf_req).done(function(extract_data, videojs_plugin, slider_plugin){
        console.log("Creating the video presentation previewer");
        console.log(extract_data);

        // inject our function to navigate through the video
        jQuery.video_jump = function video_jump(seconds) {
            videojs('mypresentationvideo').play();
            videojs('mypresentationvideo').pause();
            videojs('mypresentationvideo').currentTime(seconds);
            videojs('mypresentationvideo').play();
        };

        // initialise our slider
        var navSlider = document.createElement("section");
        navSlider.className = "center slider";
        var mainSlider = document.createElement("section");
        mainSlider.className = "regular slider";

        // create the WebVTT file: first the mandatory header
        var vtt_list = ["WEBVTT", ""];
        var slide, slide_image;

        try {
            extract_data[0][0]['content']['listslides'].forEach(function(elem, index){
                // Add to our navigation
                slide = document.createElement("div");
                slide.setAttribute("onclick", "$.video_jump(" + elem[3] + ")");
                slide_image = document.createElement("IMG");
                slide_image.setAttribute("src", jsRoutes.api.Previews.download(elem[2]).url);
                slide_image.setAttribute("title", "Click/tap on this slide to navigate to it in the video");
                slide_image.setAttribute("alt", "Slide " + (index+1));
                slide.appendChild(slide_image);
                mainSlider.appendChild(slide);
                slide = document.createElement("div");
                slide_image = document.createElement("IMG");
                slide_image.setAttribute("src", jsRoutes.api.Previews.download(elem[2]).url);
                slide_image.setAttribute("title", "Slide " + (index+1));
                slide.appendChild(slide_image);
                navSlider.appendChild(slide);
                // Add to VTT
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
        var sources;
        if(confId == fileId){
            try {
                sources = "<source src='" + jsRoutes.api.Previews.download(extract_data[0][0]['content']['previews']['mp4']).url + "' type='video/mp4'>";
                sources += "<source src='" + jsRoutes.api.Previews.download(extract_data[0][0]['content']['previews']['webm']).url + "' type='video/webm'>";
            } catch(err) {
                sources = "<source src='" + referenceUrl + "' type='video/mp4'>";
            };
            $(useTab).append(
                "<video  crossorigin='anonymous' id='mypresentationvideo' class='video-js vjs-fluid vjs-default-skin' controls preload='auto' data-setup='{}'>" +
                sources +
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

            // Add our slider
            $(useTab).append("<br/>");
            $(useTab).append(mainSlider);
            $(useTab).append("<br/>");
            $(useTab).append(navSlider);
            initialise_slick();

            // Collapse the extractor info
            $('.collapse').collapse("hide");
        }

    }).fail(function(err){
        console.log("Failed to load all scripts for video presentation previewer: " + err['status'] + " - " + err['statusText']);
    });
    
}(jQuery, Configuration));
