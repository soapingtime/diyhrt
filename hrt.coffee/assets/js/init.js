

$(document).ready( function () {

spawn_tooltips();

    $('#generate_spreadsheet').dataTable( {
        "drawCallback": function( settings ) {
            spawn_tooltips();
        },
        columnDefs: [
       { type: 'any-number', targets : [1,2,3,4] }
        ]
    } );

    $('#generate_other').dataTable( {
        "drawCallback": function( settings ) {
            spawn_tooltips();
        }
    } );


    $('.copy-text').each(function(index) {
        $(this).on("click", function(){
            $(this).select();
            document.execCommand("copy"); 
            $('.tipsy').html('Copied!');
        });
    });

});