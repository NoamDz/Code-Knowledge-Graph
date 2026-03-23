var Container = {};

Container._sendRequest = function(method, url, params, callback, data, extra) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, url, true);
    xhr.send(JSON.stringify(params));
};

var backwardCommunicator = {
    _sendRequest: Container._sendRequest
};

function assessUser(userId) {
    Container._sendRequest(
        "POST",
        "/api/assess",
        {user_id: userId},
        handleResponse,
        {session: "abc"},
        {timeout: 30000}
    );
}

function getDevices(userId) {
    Container._sendRequest(
        "POST",
        "/api/get_devices",
        null,
        onDevicesReceived,
        {user_id: userId}
    );
}

function sendBackward(data) {
    backwardCommunicator._sendRequest(
        "POST",
        "/api/backward",
        data,
        handleBackwardResponse
    );
}
