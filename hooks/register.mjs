import { register as registerSettings } from './plugin-settings.mjs';
import { register as registerResponseValidation } from './response-validation/register.mjs';

export function register(on) {
  registerSettings(on);
  registerResponseValidation(on);
}
