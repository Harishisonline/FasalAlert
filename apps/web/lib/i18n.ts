import en from '@/messages/en.json';
import mr from '@/messages/mr.json';
import hi from '@/messages/hi.json';
import { formatMessage, type MessageValues } from './icu';
import { intlLocale, type Locale } from './locales';

export type Messages = Record<string, string>;

const MESSAGES: Record<Locale, Messages> = { en, mr, hi } as Record<Locale, Messages>;

export function getMessages(locale: Locale): Messages {
  return MESSAGES[locale];
}

export type Translator = ((key: string, values?: MessageValues) => string) & { locale: Locale };

export function createTranslator(locale: Locale, messages: Messages = getMessages(locale)): Translator {
  const il = intlLocale(locale);
  const fallback = MESSAGES.en;
  const t = ((key: string, values: MessageValues = {}) => {
    const message = messages[key] ?? fallback[key];
    if (message === undefined) {
      if (process.env.NODE_ENV !== 'production') console.warn(`[i18n] missing key ${key}`);
      return key;
    }
    try {
      return formatMessage(message, values, il);
    } catch {
      return message;
    }
  }) as Translator;
  t.locale = locale;
  return t;
}
