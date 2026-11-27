import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  // Dev-Server blockiert sonst JS-Chunks, wenn die Seite ueber 127.0.0.1 statt localhost geoeffnet wird.
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
