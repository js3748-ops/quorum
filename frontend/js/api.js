const API_BASE_URL = "http://127.0.0.1:8000";

class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : detail?.reason || "Request failed.");
    this.status = status;
    this.detail = detail;
  }
}

async function apiRequest(path, options = {}) {
  const { allowUnauthorized = false, ...fetchOptions } = options;
  const headers = new Headers(fetchOptions.headers || {});
  if (fetchOptions.body && !(fetchOptions.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...fetchOptions,
    headers,
    credentials: "include",
  });
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (response.status === 401 && !allowUnauthorized) {
    window.location.href = "login.html";
    throw new ApiError(401, "Authentication required.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, data?.detail || "Request failed.");
  }
  return data;
}

window.QuorumAPI = {
  baseUrl: API_BASE_URL,
  get: (path, options = {}) => apiRequest(path, options),
  post: (path, body, options = {}) =>
    apiRequest(path, { ...options, method: "POST", body: JSON.stringify(body || {}) }),
  put: (path, body, options = {}) =>
    apiRequest(path, { ...options, method: "PUT", body: JSON.stringify(body || {}) }),
  ApiError,
};
