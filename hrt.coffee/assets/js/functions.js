_anyNumberSort = function(a, b, high) {
    var reg = /[+-]?((\d+(\.\d*)?)|\.\d+)([eE][+-]?[0-9]+)?/;       
    a = a.replace(',','.').match(reg);
    a = a !== null ? parseFloat(a[0]) : high;
    b = b.replace(',','.').match(reg);
    b = b !== null ? parseFloat(b[0]) : high;
    return ((a < b) ? -1 : ((a > b) ? 1 : 0));   
}
 
jQuery.extend( jQuery.fn.dataTableExt.oSort, {
    "any-number-asc": function (a, b) {
        return _anyNumberSort(a, b, Number.POSITIVE_INFINITY);
    },
    "any-number-desc": function (a, b) {
        return _anyNumberSort(a, b, Number.NEGATIVE_INFINITY) * -1;
    }
});

function spawn_tooltips() {
    $('.tooltips').tipsy({
        arrowWidth: 10, //arrow css border-width + margin-(left|right), default is 5 + 5
        attr: 'data-tipsy', //default attributes for tipsy - data-tipsy-position | data-tipsy-offset | data-tipsy-disabled
        cls: null, //tipsy custom class
        duration: 150, //tipsy fadeIn, fadeOut duration
        offset: 7, //tipsy offset from element
        position: 'top-center', //tipsy position - top-left | top-center | top-right | bottom-left | bottom-center | bottom-right | left | right
        trigger: 'hover', // how tooltip is triggered - hover | focus | click | manual
        onShow: null, //onShow event
        onHide: null //onHide event
    });
}

function inputCopy(e) {
    e.select();
    document.execCommand("copy"); 
    $('.tipsy').html('Copied!');
}