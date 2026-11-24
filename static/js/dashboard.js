// Draws the four dashboard charts from the JSON the view puts in #chart-data.
// Colours come from the same CSS variables as the rest of the page.
(function () {
  const data = JSON.parse(document.getElementById('chart-data').textContent);
  const css = getComputedStyle(document.documentElement);
  const colour = (name) => css.getPropertyValue(`--color-${name}`).trim();

  const primary = colour('primary-600');
  const slate = colour('slate-500');
  const grid = colour('slate-200');

  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = colour('slate-600');
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.maintainAspectRatio = false;

  const axis = (title, extra = {}) => ({
    title: { display: true, text: title, color: colour('slate-700'), font: { weight: '600' } },
    grid: { color: grid },
    ...extra,
  });
  const countAxis = (title) => axis(title, { beginAtZero: true, ticks: { precision: 0 } });

  // 1. Which skills are employers asking for most?
  new Chart(document.getElementById('chart-top-skills'), {
    type: 'bar',
    data: {
      labels: data.topSkills.labels,
      datasets: [{ label: 'Jobs', data: data.topSkills.values, backgroundColor: primary, borderRadius: 4 }],
    },
    options: {
      indexAxis: 'y',
      scales: { x: countAxis('Jobs asking for the skill'), y: axis('Skill', { grid: { display: false } }) },
    },
  });

  // 2. Is demand for those skills rising or falling? Shades of one colour plus
  // different dash patterns, so the lines stay apart without new colours.
  const shades = ['primary-800', 'primary-600', 'primary-400', 'slate-500', 'slate-400'];
  const dashes = [[], [6, 4], [2, 3], [], [6, 4]];
  new Chart(document.getElementById('chart-trend'), {
    type: 'line',
    data: {
      labels: data.trend.labels,
      datasets: data.trend.series.map((s, i) => ({
        label: s.label,
        data: s.values,
        borderColor: colour(shades[i % shades.length]),
        backgroundColor: colour(shades[i % shades.length]),
        borderDash: dashes[i % dashes.length],
        borderWidth: 2,
        pointRadius: 2,
        cubicInterpolationMode: 'monotone',
      })),
    },
    options: {
      plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 24, boxHeight: 2 } } },
      interaction: { mode: 'index', intersect: false },
      scales: { x: axis('Week starting'), y: countAxis('Jobs posted') },
    },
  });

  // 3. What level are employers hiring at? "Not stated" in grey so it doesn't read as a level.
  const levelColours = data.seniority.labels.map((l) => (l === 'Not stated' ? slate : primary));
  new Chart(document.getElementById('chart-seniority'), {
    type: 'bar',
    data: {
      labels: data.seniority.labels,
      datasets: [{ label: 'Jobs', data: data.seniority.values, backgroundColor: levelColours, borderRadius: 4 }],
    },
    options: { scales: { x: axis('Seniority', { grid: { display: false } }), y: countAxis('Jobs') } },
  });

  // 4. How many roles can be done remotely?
  const modeColours = data.workMode.labels.map((l) => (l === 'Not stated' ? slate : primary));
  new Chart(document.getElementById('chart-work-mode'), {
    type: 'bar',
    data: {
      labels: data.workMode.labels,
      datasets: [{ label: 'Jobs', data: data.workMode.values, backgroundColor: modeColours, borderRadius: 4 }],
    },
    options: { scales: { x: axis('Work mode', { grid: { display: false } }), y: countAxis('Jobs') } },
  });
})();
