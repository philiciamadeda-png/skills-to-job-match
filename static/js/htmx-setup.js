// Leave empty filters out of HTMX requests, so URLs read /jobs/?q=python
// rather than /jobs/?q=python&seniority=&work_mode=&source=
document.addEventListener('htmx:configRequest', (event) => {
  const params = event.detail.parameters;
  for (const key of Array.from(params.keys())) {
    if (params.get(key) === '') params.delete(key);
  }
});
