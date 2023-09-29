function switchButton() {
    var currentTheme = document.documentElement.getAttribute("data-theme");
    
    if (currentTheme === "dark") {
        $('#dark-toggle').html("<span class='icon-fa5-sun'></span>");
    } else {
        $('#dark-toggle').html("<span class='icon-fa5-moon'></span>");
    }
}

$( document ).ready(function() {
    var darkToggle = document.getElementById("dark-toggle");
    darkToggle.onclick = function() {
        event.preventDefault();
        var currentTheme = document.documentElement.getAttribute("data-theme");
        var switchToTheme = currentTheme === "dark" ? "light" : "dark"
        document.documentElement.setAttribute("data-theme", switchToTheme);
        
        if (switchToTheme === "dark") {
            localStorage.darkmode = "1";
            console.log("Night theme enabled, localStorage.darkmode = "+localStorage.darkmode);
        } else {
            localStorage.darkmode = "0";
            console.log("Day theme enabled, localStorage.darkmode = "+localStorage.darkmode);
        }
        
        switchButton();
    }

    switchButton();
});