import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Type system (self-hosted, bundled — no runtime CDN). Latin subset only;
// CJK falls back to PingFang SC / Microsoft YaHei.
//   Hanken Grotesk — humanist sans for UI text
//   Fraunces       — editorial serif for masthead, brand wordmark, metric numerals
//   IBM Plex Mono  — identifiers, timestamps, instrument figures
import "@fontsource/hanken-grotesk/latin-400.css";
import "@fontsource/hanken-grotesk/latin-500.css";
import "@fontsource/hanken-grotesk/latin-600.css";
import "@fontsource/hanken-grotesk/latin-700.css";
import "@fontsource/fraunces/latin-400.css";
import "@fontsource/fraunces/latin-500.css";
import "@fontsource/fraunces/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import App from "./App";

window.addEventListener("unhandledrejection", (event) => {
  console.error("Unhandled promise rejection:", event.reason);
});
window.addEventListener("error", (event) => {
  console.error("Uncaught error:", event.error);
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
