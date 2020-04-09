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
    var i, s, len, myCssFiles = [ "/video-js.min.css", "/presentationvideo.css", "/slick/slick.css", "/slick/slick-theme.css", "/slickconf.css" ];
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
        url: Configuration.previewer + "/video.min.js",
        dataType: "script",
        context: this,
    });

    // only load the plugin after Video.js itself has been loaded.
    var videojs_chapter_plugin = $.when(videojs_req).then(function() {
        return $.ajax({
            url: Configuration.previewer + "/videojs-chapter-nav/videojs.chapter-nav.min.js",
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

    // Create a toggle for all metadata
    toggleMetadata = function(){
        var small = "col-md-4 col-sm-4 col-lg-4"
        var medium = "col-md-8 col-sm-8 col-lg-8"
        var large = "col-md-12 col-sm-12 col-lg-12"
        // First small item is the file metadata
        var fileMetadata = document.getElementsByClassName(small)[0];
        if (fileMetadata.style.display === "none") {
            fileMetadata.style.display = "block";
            // Shrink the main div
            mainDiv = document.getElementsByClassName(large)[0];
            mainDiv.className = medium
        } else {
            fileMetadata.style.display = "none";
            // Expand the main div
            mainDiv = document.getElementsByClassName(medium)[0];
            mainDiv.className = large
        }
    }

    activateComments = function(){
        var tabclass = "nav nav-tabs margin-bottom-20"
        var tabs = document.getElementsByClassName(tabclass)[0].getElementsByTagName("li");
        // Make 3rd tab active
        tabs[0].classList.remove("active");
        tabs[2].classList.add("active");
        document.getElementById("tab-metadata").classList.remove("active", "in");
        document.getElementById("tab-comments").classList.add("active", "in");
    }

    // when all the plugins and the JSON-LD are loaded, we can show the previewer
    $.when(extractor_req, videojs_chapter_plugin, slickconf_req).done(function(extract_data, videojs_plugin, slider_plugin){
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

        // create an array of slide times so that we can implement jumping to slide based on time in video
        var slide_times=[];

        try {
            extract_data[0][0]['content']['listslides'].forEach(function(elem, index){
                // Add to our navigation
                slide = document.createElement("div");
                // Add to the array of slide times
                slide_times.push(elem[3]);
                slide.setAttribute("onclick", "$.video_jump(" + elem[3] + ")");
                slide_image = document.createElement("IMG");
                slide_image.setAttribute("data-lazy", jsRoutes.api.Previews.download(elem[2]).url);
                slide_image.setAttribute("title", "Slide " + (index+1) + "/" + extract_data[0][0]['content']['nrslides'] + " : Click/tap on this slide to navigate to it in the video");
                slide_image.setAttribute("alt", "Slide " + (index+1) + "/" + extract_data[0][0]['content']['nrslides']);
                slide.appendChild(slide_image);
                mainSlider.appendChild(slide);
              
                slide = document.createElement("div");
                slide_image = document.createElement("IMG");
                slide_image.setAttribute("data-lazy", jsRoutes.api.Previews.download(elem[2]).url);
                slide_image.setAttribute("title", "Slide " + (index+1) + "/" + extract_data[0][0]['content']['nrslides']);
                slide.appendChild(slide_image);
                navSlider.appendChild(slide);
                // Add to VTT
                vtt_list.push((index+1));
                vtt_list.push(elem[0] + " --> " + elem[1]);
                // Adding thumbnail images for chapters is possible via https://github.com/chemoish/videojs-chapter-thumbnails (videojs v5)
                // Adding images to the chapters has high overhead, they are not cached and are loaded before the video begins to play
                //vtt_list.push('{"title":"Slide ' + (index+1) + '", "image": "'+ jsRoutes.api.Previews.download(elem[2]).url +'"}');
                vtt_list.push('Slide ' + (index+1));
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
                if( 'webm' in extract_data[0][0]['content']['previews'] ){
                    sources += "<source src='" + jsRoutes.api.Previews.download(extract_data[0][0]['content']['previews']['webm']).url + "' type='video/webm'>";
                }
            } catch(err) {
                sources = "<source src='" + referenceUrl + "' type='video/mp4'>";
            };
            $(useTab).append(
                "<video  crossorigin='anonymous' id='mypresentationvideo' class='video-js vjs-fluid vjs-default-skin' controls preload='auto' data-setup='{ \"playbackRates\": [0.75, 1, 1.25, 1.5, 1.75] }'>" +
                sources +
                "<track kind='chapters' src='data:text/plain;base64,"+ window.btoa(webvtt) +"' label=\"Slides\" default>" +
                "<p class='vjs-no-js'>" +
                "To view this video consider upgrading to a web browser that " +
                "<a href='http://videojs.com/html5-video-support/' target='_blank'>supports HTML5 video.</a></p>" +
                "</video>"
            );
            // initialize the video element just added + plugin
            videojs('mypresentationvideo').ready(function(){
              this.chapterNav();
            }); 

            // Add our slider
            $(useTab).append("<br/>");
            $(useTab).append("<div><h3 style=\"text-align:center;\"><label class=\"switch\">\
              <input type=\"checkbox\" checked id=\"switchsync\">\
              <span  title=\"Turn off to use slides for navigation\" class=\"mytoggle round\"></label>\
              <em>Sync video to slides</em></h3><div>");
            $(useTab).append("<br/>");
            $(useTab).append(mainSlider);
            $(useTab).append("<br/>");
            $(useTab).append(navSlider);
            initialise_slick();

            // Jump to slide in slick based on what the current time in the video is. Since  the slide time array is an
            // ordered list, we just need to find the index of the element that matches.
            function findSlide(element){
              return  this < element;
            }

            videojs('mypresentationvideo').on('timeupdate', function(e) {
              // Check if we sync or not
              if (document.getElementById("switchsync").checked) {
                var next_slide = slide_times.findIndex(findSlide, videojs('mypresentationvideo').currentTime());
                // Set current slide (with exception of last slide where findIndex returns -1)
                if (next_slide >= 0) {
                  $('.regular').slick('slickGoTo', next_slide - 1);
                } else {
                  // Explicitly set to last slide
                  $('.regular').slick('slickGoTo', slide_times.length - 1);
                }
              }
            });
        }

        // Collapse the extractor accordian info
        $('.collapse').collapse("hide");

        $(Configuration.tab).append("<br /><br /><button onclick=\"toggleMetadata()\">Toggle metadata for this item</button>");

        // Once the page is loaded, give a default wide view and sure comments are the active tab
        window.addEventListener("load", function(){
            toggleMetadata();
            activateComments();
        });

    }).fail(function(err){
        console.log("Failed to load all scripts for video presentation previewer: " + err['status'] + " - " + err['statusText']);
    });

}(jQuery, Configuration));

