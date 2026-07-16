export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl items-center justify-center px-6 py-20">
      <div className="flex flex-col gap-2 text-center">
        <h1 className="text-2xl font-semibold text-[var(--ant-color-text)]">404</h1>
        <p className="text-sm text-[var(--ant-color-text-secondary)]">This page could not be found.</p>
      </div>
    </main>
  );
}
