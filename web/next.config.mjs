/**
 * SPECTRE web — Next.js config
 * Author: gurvinny
 */
/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output for a small Docker runtime image.
  output: "standalone",
  reactStrictMode: true,
  // Allow the dev server to be reached over the LAN host IP (cross-origin dev).
  allowedDevOrigins: ["10.0.0.10"],
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8100",
  },
};

export default nextConfig;
