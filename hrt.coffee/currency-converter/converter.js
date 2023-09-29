$(document).ready( function () {
if(!$("span#currency-container").length == 0) {
//set a default currency
if (typeof localStorage.currency === 'undefined') {
	localStorage.currency = 'USD';
	 console.log('No currency stored, Default ' + localStorage.currency + ' Selected.');
}

$("#currency-container").append("<select id=\"currencySelector\"></select>");

var 
    selector = document.getElementById("currencySelector");
var
    currencyElements = document.getElementsByClassName("currency");

selector.innerHTML = `
    <option value="usd">USD</option>
    <option value="eur">EUR</option>
    <option value="gbp">GBP</option>
    <option value="cad">CAD</option>
    <option value="aud">AUD</option>
    <option value="nok">NOK</option>
    <option value="disabled">none</option>
`;


//enable default
selector.value = localStorage.currency.toLowerCase();
console.log(localStorage.currency + ' Selected.');
    
var
    currencySymbols = {
        USD: "$",
        EUR: "&euro;",
        GBP: "&pound;",
        NOK: "kr",
        AUD: "$",
        CAD: "$"
    };

function curconvert() {
    if (localStorage.currency != 'DISABLED') {
        var 
            toCurrency = selector.value.toUpperCase();
            
        var
            currencySymbol = currencySymbols[toCurrency];
    
        for (var i=0,l=currencyElements.length; i<l; ++i) {
            var 
                el = currencyElements[i];
            var 
                fromCurrency = el.getAttribute("data-currencyName").toUpperCase();
          
            if (fromCurrency in usdChangeRate) {
                var 
                    fromCurrencyToUsdAmount = parseFloat(el.innerHTML) / usdChangeRate[fromCurrency];
                var 
                    toCurrencyAmount = fromCurrencyToUsdAmount * usdChangeRate[toCurrency];
                
                el.innerHTML = toCurrencyAmount.toFixed(2) + "<span>" + currencySymbol + "</span>";
                el.setAttribute("data-currencyName",toCurrency);
            }
        }
    }
}

//run function
curconvert();

//on currency selection, save selected to browser and run again
selector.onchange = function() {
    localStorage.currency = selector.value.toUpperCase();
    console.log(localStorage.currency + ' Selected.');

    curconvert();
    
    if (localStorage.currency == 'DISABLED') {
        location.reload();    
    }
}
}
} );