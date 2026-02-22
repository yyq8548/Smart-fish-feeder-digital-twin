const temperatureEl = document.getElementById("temperature");
const coolingStatusEl = document.getElementById("coolingStatus");
const pumpStatusEl = document.getElementById("pumpStatus");
const eventLogEl = document.getElementById("eventLog");
const feedBtn = document.getElementById("feedBtn");
const cleanBtn = document.getElementById("cleanBtn");
const systemHealthEl = document.getElementById("systemHealth");

const TEMP_LOW = 3.0;
const TEMP_HIGH = 5.0;

let currentTemp = 4.4;
let pumpState = "IDLE";

const labels = [];
const tempData = [];

function nowLabel() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function addLog(message) {
  const li = document.createElement("li");
  li.textContent = `[${nowLabel()}] ${message}`;
  eventLogEl.prepend(li);

  while (eventLogEl.children.length > 8) {
    eventLogEl.removeChild(eventLogEl.lastChild);
  }
}

function simulateTemperature() {
  const drift = (Math.random() - 0.5) * 0.35;
  currentTemp = Math.max(2.4, Math.min(6.2, currentTemp + drift));

  if (currentTemp > TEMP_HIGH) {
    coolingStatusEl.textContent = "ON";
    systemHealthEl.textContent = "Cooling Active";
    systemHealthEl.style.background = "#e8f1fb";
    systemHealthEl.style.color = "#1e6da8";
    currentTemp -= 0.25;
  } else if (currentTemp < TEMP_LOW) {
    coolingStatusEl.textContent = "OFF";
    systemHealthEl.textContent = "Below Target";
    systemHealthEl.style.background = "#fff6e5";
    systemHealthEl.style.color = "#9a6300";
  } else {
    coolingStatusEl.textContent = "OFF";
    systemHealthEl.textContent = "System Normal";
    systemHealthEl.style.background = "#e8f6ee";
    systemHealthEl.style.color = "#1f7a43";
  }

  temperatureEl.textContent = currentTemp.toFixed(1);

  labels.push(nowLabel());
  tempData.push(Number(currentTemp.toFixed(2)));

  if (labels.length > 20) {
    labels.shift();
    tempData.shift();
  }

  chart.update();
}

function setPumpState(state, durationMs) {
  pumpState = state;
  pumpStatusEl.textContent = state;
  addLog(`Pump state changed to ${state}`);

  if (durationMs) {
    setTimeout(() => {
      pumpState = "IDLE";
      pumpStatusEl.textContent = "IDLE";
      addLog("Pump returned to IDLE");
    }, durationMs);
  }
}

feedBtn.addEventListener("click", () => {
  setPumpState("FEEDING", 3000);
  addLog("Manual feed command triggered");
});

cleanBtn.addEventListener("click", () => {
  setPumpState("CLEANING", 3000);
  addLog("Reverse-pump cleaning triggered");
});

const ctx = document.getElementById("tempChart");
const chart = new Chart(ctx, {
  type: "line",
  data: {
    labels,
    datasets: [
      {
        label: "Reservoir Temperature (°C)",
        data: tempData,
        tension: 0.35
      }
    ]
  },
  options: {
    responsive: true,
    scales: {
      y: {
        suggestedMin: 2,
        suggestedMax: 7
      }
    }
  }
});

addLog("Dashboard initialized");
setInterval(simulateTemperature, 1200);