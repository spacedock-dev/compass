/* Only the recorded UI note changes. Session words stay intact, including a title that quotes the
   retired warning. The separate mounted tests and Storybook hold the new location cards and routes. */
export function recordedLocationNotes(record, payload, project = '') {
  const rows = Array.isArray(payload?.sessions) ? payload.sessions : [];
  const noteFor = (label) => {
    const members = rows.filter((row) => row.project === label);
    const measured = members.filter(
      (row) =>
        ['git common directory', 'working directory path'].includes(row.project_identity_source) &&
        typeof row.project_key === 'string' &&
        row.project_key.trim(),
    );
    const locations = new Set(measured.map((row) => row.project_key.trim()));
    const unknown = members.length - measured.length;
    return {
      before: `${members.length} sessions share this display label; shared location is not established`,
      after: [
        locations.size > 1
          ? `${members.length} sessions share this display label across ${locations.size} measured locations`
          : '',
        unknown
          ? `Location not measured for ${unknown} ${unknown === 1 ? 'session' : 'sessions'} with this display label`
          : '',
      ]
        .filter(Boolean)
        .join('. '),
    };
  };
  const replace = (text, label, title = '') => {
    if (typeof text !== 'string' || !label) return text;
    const { before, after } = noteFor(label);
    const start = title && text.includes(title) ? text.indexOf(title) + title.length : 0;
    const at = text.indexOf(before, start);
    return at < 0 ? text : text.slice(0, at) + after + text.slice(at + before.length);
  };
  const walk = (value) => {
    if (Array.isArray(value)) return value.map(walk);
    if (!value || typeof value !== 'object') return value;
    const result = Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, walk(item)]),
    );
    const source = rows.find((row) => row.harness === value.harness && row.sid === value.sid);
    if (typeof value.project === 'string') result.text = replace(value.text, value.project);
    else if (source && typeof value.text === 'string')
      result.text = replace(value.text, source.project, source.title);
    if (project && typeof value.header === 'string') result.header = replace(value.header, project);
    return result;
  };
  return walk(record);
}

export function unchangedAttentionLocations(summary) {
  return {
    ...summary,
    sections: summary.sections.map((section) => ({
      ...section,
      items: section.items.filter((item) => !/^(collision|checkout):/.test(item.subject)),
    })),
  };
}
