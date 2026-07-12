export class TelemetryLineChart {
  constructor(canvas, config = {}) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.data = config.data ?? { labels: [], datasets: [{ data: [] }] };
    this.options = config.options ?? {};
    this.update();
  }

  update() {
    const context = this.context;
    if (!context) return;

    const bounds = this.canvas.getBoundingClientRect();
    const width = Math.max(320, Math.round(bounds.width || this.canvas.parentElement?.clientWidth || 640));
    const height = Math.max(220, Math.round(bounds.height || 300));
    const pixelRatio = Math.max(1, globalThis.devicePixelRatio || 1);
    const targetWidth = Math.round(width * pixelRatio);
    const targetHeight = Math.round(height * pixelRatio);
    if (this.canvas.width !== targetWidth || this.canvas.height !== targetHeight) {
      this.canvas.width = targetWidth;
      this.canvas.height = targetHeight;
    }
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    const margin = { top: 34, right: 20, bottom: 38, left: 50 };
    const plotWidth = Math.max(1, width - margin.left - margin.right);
    const plotHeight = Math.max(1, height - margin.top - margin.bottom);
    const labels = this.data.labels ?? [];
    const rawValues = this.data.datasets?.[0]?.data ?? [];
    const values = rawValues.map((value) => value === null ? null : Number(value));
    const finiteValues = values.filter((value) => value !== null && Number.isFinite(value));
    const configuredMin = Number(this.options.scales?.y?.suggestedMin ?? 2);
    const configuredMax = Number(this.options.scales?.y?.suggestedMax ?? 7);
    const dataMin = finiteValues.length ? Math.min(...finiteValues) : configuredMin;
    const dataMax = finiteValues.length ? Math.max(...finiteValues) : configuredMax;
    const yMin = Math.floor(Math.min(configuredMin, dataMin));
    const yMax = Math.ceil(Math.max(configuredMax, dataMax, yMin + 1));

    context.font = "12px Inter, system-ui, sans-serif";
    context.lineWidth = 1;
    context.textBaseline = "middle";
    for (let step = 0; step <= 5; step += 1) {
      const fraction = step / 5;
      const y = margin.top + plotHeight * fraction;
      const value = yMax - (yMax - yMin) * fraction;
      context.strokeStyle = "rgba(22, 55, 75, 0.12)";
      context.beginPath();
      context.moveTo(margin.left, y);
      context.lineTo(margin.left + plotWidth, y);
      context.stroke();
      context.fillStyle = "#60717c";
      context.textAlign = "right";
      context.fillText(value.toFixed(1), margin.left - 9, y);
    }

    context.fillStyle = "#60717c";
    context.textAlign = "left";
    context.fillText("Reservoir temperature (°C)", margin.left, 14);

    if (finiteValues.length === 0) {
      context.fillStyle = "#60717c";
      context.textAlign = "center";
      context.fillText("Waiting for telemetry", margin.left + plotWidth / 2, margin.top + plotHeight / 2);
      return;
    }

    const xFor = (index) => margin.left + (values.length <= 1 ? plotWidth / 2 : (index / (values.length - 1)) * plotWidth);
    const yFor = (value) => margin.top + ((yMax - value) / (yMax - yMin)) * plotHeight;
    context.strokeStyle = "#2094cf";
    context.lineWidth = 3;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.beginPath();
    let lineStarted = false;
    values.forEach((value, index) => {
      if (value === null || !Number.isFinite(value)) {
        lineStarted = false;
        return;
      }
      const x = xFor(index);
      const y = yFor(value);
      if (lineStarted) context.lineTo(x, y);
      else context.moveTo(x, y);
      lineStarted = true;
    });
    context.stroke();

    context.fillStyle = "#ffffff";
    context.strokeStyle = "#2094cf";
    context.lineWidth = 2;
    values.forEach((value, index) => {
      if (value === null || !Number.isFinite(value)) return;
      context.beginPath();
      context.arc(xFor(index), yFor(value), 3.5, 0, Math.PI * 2);
      context.fill();
      context.stroke();
    });

    const labelIndexes = [...new Set([0, Math.floor((labels.length - 1) / 2), labels.length - 1])]
      .filter((index) => index >= 0 && labels[index]);
    context.fillStyle = "#60717c";
    context.textBaseline = "top";
    labelIndexes.forEach((index) => {
      context.textAlign = index === 0 ? "left" : index === labels.length - 1 ? "right" : "center";
      context.fillText(String(labels[index]), xFor(index), margin.top + plotHeight + 10);
    });
  }

  destroy() {
    this.context?.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }
}

globalThis.Chart = TelemetryLineChart;
