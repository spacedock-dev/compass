/* Only Compass-authored time phrases departed from the recorded answers. The mounted tests and
   Storybook check their new wording and placement. Keep the surrounding evidence in the comparison. */
const duration =
  /(?:\d+[smhd](?: \d+[mh])?|\d+ (?:seconds?|minutes?|hours?|days?)(?: \d+ (?:minutes?|hours?))?)/
    .source;
const clock = /\d{1,2}:\d{2}(?: [AP]M)?/.source;
const date = /[A-Z][a-z]{2} \d{1,2}(?:, \d{4})?/.source;
const iso = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z/.source;
const when = `(?:${duration} ago|yesterday|at ${clock}|on ${date}(?: at ${clock})?)`;
const epoch = /-?\d+(?:\.\d+)?/.source;

export function maskTimePhrases(value: string): string {
  return value
    .replace(new RegExp(` · stop observed(?:: ${epoch}| ${when})`, 'g'), '')
    .replace(new RegExp(` · ended ${when}`, 'g'), '')
    .replace(new RegExp(`\\bReset (?:at ${iso}|${when})`, 'g'), 'Reset <time>')
    .replace(
      new RegExp(`(Latest launch|Last recorded activity) (?:${when}|${clock})(?=\\.)`, 'g'),
      '$1 <time>',
    )
    .replace(
      new RegExp(`${duration}(?= into turn| estimated remaining| elapsed)`, 'g'),
      '<duration>',
    )
    .replace(/(Unconfirmed: no positive observation in) (?:5m|5 minutes)/g, '$1 <duration>');
}

export function maskSourceTime(value: string): string {
  return value.replace(new RegExp(` · (?:(?:waiting )?${duration}|stop observed ${when})$`), '');
}

export function maskQuotaDuration(value: string): string {
  return new RegExp(`^${duration}$`).test(value) ? '<duration>' : value;
}

export function maskReportTime(value: string): string {
  return value.replace(new RegExp(` · (?:${iso}|${when})$`), ' · <time>');
}
