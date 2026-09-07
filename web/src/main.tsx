import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import "./index.css";

// react-router has no notion of the app's deployed subpath on its own —
// without an explicit basename it matches routes against the FULL
// browser path, so at the real landing URL (/job-search-web-ui/) none
// of App.tsx's routes ("/", "/postings", "/map") match anything and the
// page renders blank, and NavLink hrefs resolve to bare "/postings"/
// "/map" instead of "/job-search-web-ui/postings" (found live
// 2026-09-07). Reusing VITE_BASE_PATH (already set correctly for Vite's
// own asset-path rewriting, see .env.production) rather than a second,
// separately-maintained literal — react-router wants no trailing slash.
const basename = import.meta.env.VITE_BASE_PATH?.replace(/\/$/, "") || undefined;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
