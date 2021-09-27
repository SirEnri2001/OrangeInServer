$("#submitButton").click(function () {
    let username = $("#username").val()
    let password = $("#password").val()
    let is_guest = $("#is_guest").checked()
    if(is_guest){
        username = "guest"
        password = "guest"
    }else{
        if(username==null){
            $(document).innerHTML = "<p>please enter username<\p>"
            return
        }
        if(password==null){
            $(document).innerHTML = "<p>please enter password<\p>"
            return
        }
    }
    $.post("http://127.0.0.1:8000/login/request/",{"username":username,"password":password,"is_guest":is_guest})
});