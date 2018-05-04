//configure the slider
function initialise_slick() {
  $(".regular").slick({
    lazyLoad: 'ondemand',
    infinite: false,
    slidesToShow: 1,
    slidesToScroll: 1,
    arrows: true,
    fade: true,
    // draggable conflicts other CSS in the preview 
    draggable: false,
    asNavFor: '.center'
  });
  $(".center").slick({
    lazyLoad: 'ondemand',
    infinite: false,
    slidesToShow: 3,
    slidesToScroll: 1,
    arrows: false,
    asNavFor: '.regular',
    // Too many slides equals too many dots
    //dots: true,
    swipeToSlide: true,
    centerMode: true,
    // draggable conflicts other CSS in the preview 
    draggable: false,
    focusOnSelect: true
  });
};

