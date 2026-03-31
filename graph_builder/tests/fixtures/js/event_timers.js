var NotificationManager = {
    init: function() {
        document.getElementById('loginForm').addEventListener('click', function(event) {
            NotificationManager.handleClick(event);
        });

        var emitter = require('./event_emitter');
        emitter.on('user-login', function(data) {
            NotificationManager.updateUI(data);
        });

        $('#form').on('submit', function(e) {
            NotificationManager.handleLogin(e);
        });
    },

    startPolling: function() {
        setTimeout(function() {
            NotificationManager.hideNotification();
        }, 3000);

        setInterval(function() {
            NotificationManager.checkStatus();
        }, 2000);

        var debounceTimer = setTimeout(function() {
            NotificationManager.processQueue();
        }, 500);
    },

    handleClick: function(event) {
        console.log('clicked');
    },

    updateUI: function(data) {
        console.log('updated');
    },

    handleLogin: function(e) {
        console.log('login');
    },

    hideNotification: function() {
        console.log('hidden');
    },

    checkStatus: function() {
        console.log('checking');
    },

    processQueue: function() {
        console.log('processing');
    }
};

module.exports = NotificationManager;
