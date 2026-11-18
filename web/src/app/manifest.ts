import type { MetadataRoute } from "next";

// Install metadata for the console; the icons are the SPECTRE mark on the scope background.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "SPECTRE",
    short_name: "SPECTRE",
    description: "Wireless intrusion detection console",
    start_url: "/",
    display: "standalone",
    background_color: "#0a0e12",
    theme_color: "#0a0e12",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
