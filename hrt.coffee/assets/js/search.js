

    //obsolete get request
    var search_value = new URL(location.href).searchParams.get('search');

    $( document ).ready(function() {
        if (search_value) {
            $('#generate_spreadsheet').DataTable().search( search_value ).draw();
            $('#generate_other').DataTable().search( search_value ).draw();
        }
    });

    //new hash search
    var search_hash = location.hash;

    $( document ).ready(function() {
        if (search_hash) {
            if (search_hash.includes('#search=')) {
                search_hash = search_hash.replace('#search=', '');
                search_hash = decodeURI(search_hash);
                $('#generate_spreadsheet').DataTable().search( search_hash ).draw();
                $('#generate_other').DataTable().search( search_hash ).draw();
            }
        }
    });

    function clearSearch() {
        document.querySelector('input[type=search]').value = '';
        $('#generate_spreadsheet').DataTable().search('').draw();
        $('#generate_other').DataTable().search('').draw();
    }

    let searchValue = '';
    let copylink = '';
    const currentPage = window.location.href.replace(location.hash,"");

    function copySearch() {
            //link to copy
        copylink = currentPage + '#search=' + searchValue;
            //Tooltip
        if ($("#copy-search").attr("data-clicked") != 1) {
            $("#copy-search").attr("data-first-title", $("#copy-search").attr("data-original-title"));
        }
        $("#copy-search").attr("data-clicked", 1);
        /*$("#copy-search")
            .tooltip('hide')
            .attr('data-original-title', "Copied!")
            .attr('data-click-title', "Copied!")
            .tooltip('update')
            .tooltip('show');*/

        $(".tipsy").html("Copied!");

        $( "#copy-search" ).mouseout(function() {
           $("#copy-search").attr('data-original-title', $("#copy-search").attr("data-first-title"));
        });
            //Copy Text
        let copyfield = document.createElement("textarea");
        copyfield.style.position = 'absolute';
        copyfield.style.left = '-999px';
        copyfield.setAttribute('readonly', '');
        document.body.appendChild(copyfield);
        copyfield.value = copylink;
        copyfield.select();
        document.execCommand("copy");
        document.body.removeChild(copyfield); 
    }

    function createClearButton() {
        let newNode = document.createElement("button");
        let parNode = document.querySelector('input[type=search]').parentNode;
        let refNode = document.querySelector('input[type=search]');
        newNode.setAttribute('id', 'clear-search');
        newNode.setAttribute('class', 'searcher');
        newNode.setAttribute('onclick', 'clearSearch()');
        newNode.setAttribute('style', 'color:inherit;border:none;position:relative;background-color:transparent;float:right;margin-left:-2rem;margin-top:0.3rem;appearance:none;margin-right:0.5rem;opacity:0.5;line-height:1;font-size:1rem;');
        newNode.innerHTML = '<span class="icon-fa5-times"></span>';
        parNode.insertBefore(newNode, refNode);
    }

    function createLinkShare() {
        let newNode = document.createElement("button");
        let parNode = document.querySelector('input[type=search]').parentNode;
        let refNode = document.querySelector('input[type=search]');
        newNode.setAttribute('id', 'copy-search');
        newNode.setAttribute('class', 'tooltips');
        newNode.setAttribute('onclick', 'copySearch()');
        newNode.setAttribute('data-toggle', 'searcher tooltip');
        newNode.setAttribute('title', 'Copy Search Link');
        newNode.setAttribute('data-original-title', 'Copy Search Link');
        newNode.setAttribute('data-click-title', 'Copied!');
        newNode.setAttribute('style', 'color:inherit;border:none;background-color:transparent;margin-left:0.3rem;margin-top:0.1rem;appearance:none;margin-right:-0.2rem;opacity:0.7;color:inherit;line-height:1;font-size:1rem;');
        newNode.innerHTML = '<span class="icon-fa5-link"></span>';
        parNode.insertBefore(newNode, refNode);
    }

    function checkSearch() {
        if (document.querySelector('input[type=search]')) {
            if (document.querySelector('input[type=search]').value != '') {
                createClearButton(); //initialize if page starts with search
                createLinkShare();
                spawn_tooltips();
                let searchValue = '';
                searchValue = encodeURIComponent(document.querySelector('input[type=search]').value);
            }
        }
    }

    $( document ).ready(function() {
        if ($('#generate_spreadsheet').length) {
            var table = $('#generate_spreadsheet').DataTable();
        } else {
            var table = $('#generate_other').DataTable();
        }
        table.on( 'search.dt', function () {
            searchValue = encodeURIComponent(document.querySelector('input[type=search]').value);

            //if search is not empty
            if (document.querySelector('input[type=search]').value != '') {
                //add button
                if (!document.querySelector('button#clear-search')) {
                    createClearButton();
                    createLinkShare();
                    spawn_tooltips();
                }
            }
            //if search is empty
            if (document.querySelector('input[type=search]').value == '') {
                if (document.getElementById("clear-search")) {
                    document.getElementById("clear-search").remove();
                }
                if (document.getElementById("copy-search")) {
                    document.getElementById("copy-search").remove();
                }
            }

        } );

        checkSearch();

    });