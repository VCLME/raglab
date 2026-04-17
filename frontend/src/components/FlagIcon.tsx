interface Props {
  code: string;
  size?: number;
  className?: string;
}

export function FlagIcon({ code, size = 20, className }: Props) {
  const width = size;
  const height = Math.round(size * 0.66);
  switch (code) {
    case "fr":
      return (
        <svg
          viewBox="0 0 3 2"
          width={width}
          height={height}
          className={className}
          aria-hidden
          preserveAspectRatio="none"
        >
          <rect width="1" height="2" fill="#0055A4" />
          <rect x="1" width="1" height="2" fill="#FFFFFF" />
          <rect x="2" width="1" height="2" fill="#EF4135" />
        </svg>
      );
    case "en":
    case "gb":
      return (
        <svg
          viewBox="0 0 60 30"
          width={width}
          height={height}
          className={className}
          aria-hidden
          preserveAspectRatio="none"
        >
          <clipPath id="raglab-uk-t">
            <path d="M30,15 h30 v15 z v-15 h-30 z h-30 v15 z v-15 h30 z" />
          </clipPath>
          <rect width="60" height="30" fill="#012169" />
          <path d="M0,0 L60,30 M60,0 L0,30" stroke="#FFFFFF" strokeWidth="6" />
          <path
            d="M0,0 L60,30 M60,0 L0,30"
            clipPath="url(#raglab-uk-t)"
            stroke="#C8102E"
            strokeWidth="4"
          />
          <path d="M30,0 v30 M0,15 h60" stroke="#FFFFFF" strokeWidth="10" />
          <path d="M30,0 v30 M0,15 h60" stroke="#C8102E" strokeWidth="6" />
        </svg>
      );
    case "pt-BR":
    case "br":
      return (
        <svg
          viewBox="0 0 100 70"
          width={width}
          height={height}
          className={className}
          aria-hidden
          preserveAspectRatio="none"
        >
          <rect width="100" height="70" fill="#009B3A" />
          <polygon points="50,7 94,35 50,63 6,35" fill="#FEDF00" />
          <circle cx="50" cy="35" r="13" fill="#002776" />
          <path
            d="M38,32 a16,16 0 0,1 24,0"
            stroke="#FFFFFF"
            strokeWidth="1.8"
            fill="none"
          />
        </svg>
      );
    default:
      return null;
  }
}
