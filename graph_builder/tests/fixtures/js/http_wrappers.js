function sendRequest(type, url, params, callback, data, extra) {
    return Net._request({
        type: type,
        url: url,
        params: params,
        data: data
    }, callback, extra);
}

function collectData() {
    sendRequest("POST", "/api/collect", {}, function(resp) {
        console.log(resp);
    });
}

function assessRisk() {
    Net._request({
        type: "POST",
        url: "/api/assess"
    }, function(resp) {
        console.log(resp);
    });
}
