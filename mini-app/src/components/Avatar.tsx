interface AvatarProps {
  src?: string | null;
  name?: string | null;
  alt: string;
  size?: number;
}

function initialsOf(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}

export function Avatar({ src, name, alt, size = 64 }: AvatarProps): JSX.Element {
  const style = { width: size, height: size, fontSize: size / 2.5 };
  if (src) {
    return (
      <img
        src={src}
        alt={alt}
        style={style}
        className="rounded-full bg-tg-secondary-bg object-cover"
        data-testid="avatar-image"
      />
    );
  }
  return (
    <div
      style={style}
      aria-label={alt}
      role="img"
      data-testid="avatar-fallback"
      className="flex items-center justify-center rounded-full bg-tg-secondary-bg font-semibold text-tg-text"
    >
      {initialsOf(name)}
    </div>
  );
}
