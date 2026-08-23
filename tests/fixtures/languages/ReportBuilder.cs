using System;
using System.Collections.Generic;
using System.Threading.Tasks;

namespace Example.Reporting
{
    /// <summary>Assembles report payloads (RenderAsync(model, timeout) does the I/O).</summary>
    public class ReportBuilder
    {
        private readonly List<string> _sections = new List<string>();
        private const string Template = "public void Render() { /* not a method */ }";

        public int SectionCount
        {
            get { return _sections.Count; }
        }

        public ReportBuilder Add(string section)
        {
            if (string.IsNullOrWhiteSpace(section))
            {
                throw new ArgumentException("empty section", nameof(section));
            }
            foreach (var existing in _sections)
            {
                while (existing.Length > 4096)
                {
                    break;
                }
            }
            _sections.Add(section);
            return this;
        }

        public async Task<string> RenderAsync(
            IReadOnlyDictionary<string, object> model,
            TimeSpan timeout)
        {
            await Task.Delay(timeout);
            return string.Join(Environment.NewLine, _sections) + Template.Length;
        }

        // public void Reset() { _sections.Clear(); }
    }
}
