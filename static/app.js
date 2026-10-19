
const form = document.querySelector("#convertForm");
const format = document.querySelector("#formato");
const quality = document.querySelector("#calidad");
const button = document.querySelector("#convertButton");
const status = document.querySelector("#status");
const download = document.querySelector("#download");

function updateQualities() {
  const options = format.value === "mp3"
    ? [
        ["128", "128 kbps"],
        ["192", "192 kbps"],
        ["320", "320 kbps"]
      ]
    : [
        ["360", "360p"],
        ["480", "480p"],
        ["720", "720p"],
        ["1080", "1080p"]
      ];

  quality.replaceChildren();

  options.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    quality.appendChild(option);
  });
}

format.addEventListener("change", updateQualities);
updateQualities();

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const data = new FormData(form);

  button.disabled = true;
  download.hidden = true;
  status.textContent =
    "Procesando el video. No cierres esta página…";

  try {
    const response = await fetch("/api/convert", {
      method: "POST",
      body: data
    });

    if (!response.ok) {
      let message = "No se pudo convertir el video.";

      try {
        const result = await response.json();
        message = result.detail || message;
      } catch {}

      throw new Error(message);
    }

    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);

    download.href = objectUrl;
    download.download = `convertido.${format.value}`;
    download.hidden = false;
    download.textContent = "Descargar archivo convertido";
    status.textContent = "¡Conversión completada!";

    download.onclick = () => {
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
    };

  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
