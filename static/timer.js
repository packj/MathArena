var timeLimit = {{ time_limit|int }} * 60; // Convert minutes to seconds
var timerDisplay = document.getElementById("timer");

function updateTimer() {
    var minutes = Math.floor(timeLimit / 60);
    var seconds = timeLimit % 60;

    // Add leading zeros
    minutes = minutes < 10 ? "0" + minutes : minutes;
    seconds = seconds < 10 ? "0" + seconds : seconds;

    timerDisplay.textContent = minutes + ":" + seconds;

    timeLimit--;

    if (timeLimit < 0) {
        clearInterval(timerInterval);
        timerDisplay.textContent = "Time's up!";
    }
}

// Run the timer immediately when the page loads
updateTimer();

var timerInterval = setInterval(updateTimer, 1000); // Update every second
