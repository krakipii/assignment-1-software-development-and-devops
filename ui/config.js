// Where the UI finds the two services. This file is the local version, for
// docker compose. The deploy pipeline replaces it with the Azure URLs, so the
// URLs are configuration, not hard-coded in the pages.
window.APP_CONFIG = {
  customersUrl: "http://localhost:8001",
  lessonsUrl: "http://localhost:8002",
};
