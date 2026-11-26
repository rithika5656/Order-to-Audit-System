import axios from "axios";

let csrfToken = "";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL
    || (import.meta.env.VITE_API_HOST ? `https://${import.meta.env.VITE_API_HOST}/api` : "/api"),
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  if (csrfToken && ["post", "put", "patch", "delete"].includes(config.method?.toLowerCase())) {
    config.headers["X-CSRF-Token"] = csrfToken;
  }
  return config;
});

api.interceptors.response.use((response) => {
  if (response.data?.csrf_token) csrfToken = response.data.csrf_token;
  return response;
});

export default api;
