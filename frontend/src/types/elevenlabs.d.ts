/* Allow usage of the ElevenLabs convai custom element in TSX */
declare namespace JSX {
  interface IntrinsicElements {
    "elevenlabs-convai": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
      "agent-id": string;
      open?: string;
    };
  }
}
