import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = "https://multipu.fun";
  const lastModified = new Date();

  return [
    {
      url: `${baseUrl}`,
      lastModified,
      changeFrequency: "daily",
      priority: 1.0,
    },
    {
      url: `${baseUrl}/launch`,
      lastModified,
      changeFrequency: "daily",
      priority: 0.95,
    },
    {
      url: `${baseUrl}/dashboard/explore`,
      lastModified,
      changeFrequency: "hourly",
      priority: 0.9,
    },
    {
      url: `${baseUrl}/dashboard/trade`,
      lastModified,
      changeFrequency: "hourly",
      priority: 0.9,
    },
    {
      url: `${baseUrl}/dashboard/tokens`,
      lastModified,
      changeFrequency: "daily",
      priority: 0.85,
    },
    {
      url: `${baseUrl}/dashboard/launches`,
      lastModified,
      changeFrequency: "daily",
      priority: 0.85,
    },
    {
      url: `${baseUrl}/dashboard/api`,
      lastModified,
      changeFrequency: "weekly",
      priority: 0.85,
    },
    {
      url: `${baseUrl}/dashboard/earnings`,
      lastModified,
      changeFrequency: "daily",
      priority: 0.8,
    },
    {
      url: `${baseUrl}/dashboard`,
      lastModified,
      changeFrequency: "daily",
      priority: 0.8,
    },
  ];
}
