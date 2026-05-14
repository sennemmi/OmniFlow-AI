import { describe, expect, it } from 'vitest';
import { extractAllCodeChanges } from '../pipelineHelpers';

describe('pipeline code change extraction', () => {
  it('falls back to UNIT_TESTING input_data files when output_data has no files', () => {
    const result = extractAllCodeChanges(
      { testing_result: { success: true } },
      {
        files: [
          { file_path: 'app/service.py', content: 'new code', original_content: 'old code' },
        ],
      }
    );

    expect(result).toHaveLength(1);
    expect(result[0].fileName).toBe('app/service.py');
    expect(result[0].changeType).toBe('modify');
  });
});
