import { useForm } from 'react-hook-form'
import { useQuery } from '@tanstack/react-query'

interface PlaceholderFormValues {
  note: string
}

/**
 * Repository-foundation placeholder route (FND-01).
 *
 * Demonstrates minimal wiring of React Router (Data Mode), TanStack Query,
 * React Hook Form, and Tailwind CSS. No product feature or backend
 * dependency is implemented here — the query below resolves a local value
 * only, so this route renders deterministically without network access.
 */
export function PlaceholderRoute() {
  const { data: status } = useQuery({
    queryKey: ['placeholder-status'],
    queryFn: () => Promise.resolve('Repository foundation is running.'),
  })

  const { register, handleSubmit, formState, reset } =
    useForm<PlaceholderFormValues>({
      defaultValues: { note: '' },
    })

  const onSubmit = handleSubmit((values) => {
    reset({ note: values.note })
  })

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center gap-6 p-8 text-center">
      <h1 className="text-3xl font-semibold text-slate-900 dark:text-slate-100">
        TrustTable
      </h1>
      <p className="text-slate-600 dark:text-slate-400">{status}</p>
      <p className="text-sm text-slate-500 dark:text-slate-500">
        Repository foundation placeholder route. No product features are
        implemented yet.
      </p>

      <form
        onSubmit={(event) => {
          void onSubmit(event)
        }}
        aria-label="placeholder form"
        className="flex w-full flex-col gap-3"
      >
        <label
          htmlFor="note"
          className="text-left text-sm font-medium text-slate-700 dark:text-slate-300"
        >
          Placeholder field
        </label>
        <input
          id="note"
          type="text"
          className="rounded border border-slate-300 px-3 py-2 text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
          {...register('note', { required: true })}
        />
        <button
          type="submit"
          className="rounded bg-slate-900 px-4 py-2 font-medium text-white dark:bg-slate-100 dark:text-slate-900"
        >
          Submit
        </button>
        {formState.isSubmitSuccessful && (
          <p
            role="status"
            className="text-sm text-emerald-600 dark:text-emerald-400"
          >
            Submitted.
          </p>
        )}
      </form>
    </main>
  )
}
