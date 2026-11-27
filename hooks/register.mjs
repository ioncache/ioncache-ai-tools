import { register as registerSettings } from './plugin-settings.mjs';
import { register as registerResponseValidation } from './response-validation/register.mjs';
import { register as registerContextHandoff } from './context-handoff.mjs';

export function register(on) {
  registerSettings(on);
  registerResponseValidation(on);
  registerContextHandoff(on);
}
