import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const steps = [
  {
    id: "name",
    label: "First, what should we call you?",
    emphasis: "call you",
    placeholder: "Your name",
    type: "text",
    validation: (v) => v.trim().length >= 2,
    errorMsg: "Name must be at least 2 characters",
  },
  {
    id: "assistant_name",
    label: "What should we call your assistant?",
    emphasis: "your assistant",
    placeholder: "e.g. Nova",
    type: "text",
    validation: (v) => v.trim().length >= 2,
    errorMsg: "Give your assistant a name (at least 2 characters)",
  },
  {
    id: "email",
    label: "Where can we reach you?",
    emphasis: "reach you",
    placeholder: "you@example.com",
    type: "email",
    validation: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v),
    errorMsg: "Please enter a valid email",
  },
  {
    id: "phone",
    label: "And a number, in case we need it?",
    emphasis: "number",
    placeholder: "9876543210",
    type: "tel",
    validation: (v) => /^\d{10}$/.test(v.replace(/\s/g, "")),
    errorMsg: "Phone must be 10 digits",
  },
  {
    id: "address",
    label: "Where should we deliver your finds?",
    emphasis: "deliver",
    placeholder: "Your delivery address",
    type: "text",
    validation: (v) => v.trim().length >= 5,
    errorMsg: "Please enter a valid address",
  },
  {
    id: "gender",
    label: "Help us tailor your style",
    emphasis: "tailor",
    type: "options",
    options: ["Male", "Female", "Other"],
  },
  {
    id: "size",
    label: "What size do you wear?",
    emphasis: "size",
    type: "options",
    // Six options stack into an unreadable column as full-width rows, and a
    // size rail is the one thing shoppers expect to see laid out side by side.
    layout: "grid",
    options: ["XS", "S", "M", "L", "XL", "XXL"],
    hint: "We only show you shirts that are actually in stock in your size.",
  },
  {
    id: "payment_method",
    label: "How would you like to pay?",
    emphasis: "pay",
    type: "options",
    options: ["UPI", "Card", "COD"],
  },
];

function EmphasizedLabel({ label, emphasis }) {
  if (!emphasis) return label;
  const idx = label.indexOf(emphasis);
  if (idx === -1) return label;
  return (
    <>
      {label.slice(0, idx)}
      <span className="emphasis">{emphasis}</span>
      {label.slice(idx + emphasis.length)}
    </>
  );
}

const fadeVariants = {
  enter: { opacity: 0, y: 14 },
  center: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -14 },
};

export default function OnboardingScreen({ onComplete, onSkip }) {
  const [currentStep, setCurrentStep] = useState(0);
  const [values, setValues] = useState({});
  const [error, setError] = useState("");
  const [isComplete, setIsComplete] = useState(false);
  const inputRef = useRef(null);

  const step = steps[currentStep];
  const isLastStep = currentStep === steps.length - 1;
  const answeredCount = steps.filter((entry) => values[entry.id]).length;

  useEffect(() => {
    if (step?.type !== "options" && inputRef.current) {
      inputRef.current.focus();
    }
  }, [currentStep, step]);

  const validate = (value) => {
    if (step.validation && !step.validation(value)) {
      setError(step.errorMsg);
      return false;
    }
    setError("");
    return true;
  };

  const handleNext = () => {
    const value = values[step.id] || "";
    if (step.type !== "options" && !validate(value)) return;

    if (isLastStep) {
      setIsComplete(true);
      setTimeout(() => onComplete(values), 800);
      return;
    }

    setCurrentStep((prev) => prev + 1);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && values[step.id]) {
      handleNext();
    }
  };

  const handleOptionSelect = (option) => {
    setValues((prev) => ({ ...prev, [step.id]: option }));
    setTimeout(() => {
      if (isLastStep) {
        setIsComplete(true);
        setTimeout(() => onComplete({ ...values, [step.id]: option }), 800);
      } else {
        setCurrentStep((prev) => prev + 1);
      }
    }, 300);
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center p-8">
      {!isComplete && (
        <motion.button
          onClick={() => onSkip(values)}
          className="absolute top-8 right-8 text-sm text-muted-foreground transition-colors hover:text-foreground"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
        >
          Skip for now &rarr;
        </motion.button>
      )}

      <motion.div
        className="w-full max-w-xl"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      >
        {/* Progress. The bar used to fill segment `i <= currentStep`, which
            marked the step you were still answering as complete — on the last
            question every segment read as done. Completed and current are now
            distinct states, and the counter next to it is the plain fact. */}
        <div className="mb-3 flex items-baseline justify-between gap-4">
          <span className="text-xs tracking-widest text-muted-foreground uppercase">
            Step <span className="font-semibold text-primary">{currentStep + 1}</span> of{" "}
            {steps.length}
          </span>
          <span className="text-xs text-muted-foreground">
            {answeredCount} answered
          </span>
        </div>
        <div className="mb-14 flex gap-1.5">
          {steps.map((entry, i) => {
            const answered = Boolean(values[entry.id]);
            const isCurrent = i === currentStep;
            return (
              <div
                key={entry.id}
                className="h-0.5 flex-1 overflow-hidden rounded-full"
                style={{ background: "var(--color-border)" }}
              >
                <motion.div
                  className="h-full rounded-full"
                  style={{
                    background: answered ? "var(--color-primary)" : "var(--color-primary)",
                    opacity: answered ? 1 : 0.45,
                  }}
                  initial={{ width: 0 }}
                  // A stub, not a fill, for the question you're looking at: it
                  // marks where you are without claiming you've answered it.
                  animate={{ width: answered ? "100%" : isCurrent ? "30%" : "0%" }}
                  transition={{ duration: 0.4, ease: "easeOut" }}
                />
              </div>
            );
          })}
        </div>

        {/* Step content */}
        <div className="relative min-h-[260px]">
          <AnimatePresence mode="wait">
            {!isComplete ? (
              <motion.div
                key={currentStep}
                variants={fadeVariants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.45, ease: "easeInOut" }}
                className="absolute inset-0"
              >
                <h1 className="font-hero mb-10 text-3xl md:text-4xl">
                  <EmphasizedLabel label={step.label} emphasis={step.emphasis} />
                </h1>

                {step.hint && (
                  <p className="-mt-6 mb-8 text-sm text-muted-foreground">{step.hint}</p>
                )}

                {step.type === "options" ? (
                  <div
                    className={cn(
                      step.layout === "grid"
                        ? "grid grid-cols-3 gap-3 sm:grid-cols-6"
                        : "flex flex-col gap-3"
                    )}
                  >
                    {step.options.map((option) => (
                      <motion.button
                        key={option}
                        onClick={() => handleOptionSelect(option)}
                        className={cn(
                          "rounded-lg border transition-all",
                          step.layout === "grid"
                            ? "px-2 py-4 text-center text-lg font-medium"
                            : "w-full px-6 py-4 text-left text-lg",
                          "border-border hover:border-primary",
                          values[step.id] === option ? "border-primary bg-primary/10" : "bg-card"
                        )}
                        whileHover={{ scale: 1.01 }}
                        whileTap={{ scale: 0.99 }}
                      >
                        {step.layout === "grid" ? (
                          option
                        ) : (
                          <div className="flex items-center justify-between">
                            <span>{option}</span>
                            {values[step.id] === option && <Check className="h-5 w-5 text-primary" />}
                          </div>
                        )}
                      </motion.button>
                    ))}
                  </div>
                ) : (
                  <div className="relative">
                    <input
                      ref={inputRef}
                      type={step.type}
                      value={values[step.id] || ""}
                      onChange={(e) => {
                        const val =
                          step.type === "tel" ? e.target.value.replace(/[^\d]/g, "") : e.target.value;
                        setValues((prev) => ({ ...prev, [step.id]: val }));
                        setError("");
                      }}
                      onKeyDown={handleKeyDown}
                      placeholder={step.placeholder}
                      className={cn(
                        "w-full border-b-2 border-border bg-transparent px-0 py-4 text-2xl",
                        "transition-colors placeholder:text-muted-foreground focus:border-primary focus:outline-none",
                        error && "border-destructive"
                      )}
                    />
                    <AnimatePresence>
                      {error && (
                        <motion.p
                          initial={{ opacity: 0, y: -5 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0 }}
                          className="mt-2 text-sm text-destructive"
                        >
                          {error}
                        </motion.p>
                      )}
                    </AnimatePresence>
                  </div>
                )}
              </motion.div>
            ) : (
              <motion.div
                key="complete"
                className="absolute inset-0 flex flex-col items-center justify-center text-center"
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.4 }}
              >
                <motion.div
                  className="mb-6 flex size-16 items-center justify-center rounded-full bg-primary/10"
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: "spring", stiffness: 260, damping: 18, delay: 0.1 }}
                >
                  <Check className="size-8 text-primary" />
                </motion.div>
                <p className="font-hero text-2xl">
                  You&rsquo;re all <span className="emphasis">set</span>
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {!isComplete && step.type !== "options" && (
          <Button
            onClick={handleNext}
            disabled={!values[step.id]}
            size="lg"
            className="mt-8 gap-2 rounded-lg px-8 py-6 text-base font-medium"
          >
            {isLastStep ? "Complete" : "Continue"}
            <ArrowRight className="h-4 w-4" />
          </Button>
        )}
      </motion.div>
    </div>
  );
}
