import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowRight, Check } from "lucide-react";
import { cn } from "@/lib/utils";

const steps = [
  {
    id: "name",
    label: "What's your name?",
    placeholder: "Enter your name",
    type: "text",
    validation: (v) => v.trim().length >= 2,
    errorMsg: "Name must be at least 2 characters",
  },
  {
    id: "email",
    label: "What's your email?",
    placeholder: "you@example.com",
    type: "email",
    validation: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v),
    errorMsg: "Please enter a valid email",
  },
  {
    id: "phone",
    label: "What's your phone number?",
    placeholder: "9876543210",
    type: "tel",
    validation: (v) => /^\d{10}$/.test(v.replace(/\s/g, "")),
    errorMsg: "Phone must be 10 digits",
  },
  {
    id: "address",
    label: "Where should we deliver?",
    placeholder: "Enter your delivery address",
    type: "text",
    validation: (v) => v.trim().length >= 5,
    errorMsg: "Please enter a valid address",
  },
  {
    id: "gender",
    label: "What's your gender?",
    type: "options",
    options: ["Male", "Female", "Other"],
  },
  {
    id: "payment_method",
    label: "Preferred payment method?",
    type: "options",
    options: ["UPI", "Card", "COD"],
  },
];

const slideVariants = {
  enter: (direction) => ({ x: direction > 0 ? 100 : -100, opacity: 0 }),
  center: { x: 0, opacity: 1 },
  exit: (direction) => ({ x: direction > 0 ? -100 : 100, opacity: 0 }),
};

export default function OnboardingScreen({ onComplete }) {
  const [currentStep, setCurrentStep] = useState(0);
  const [values, setValues] = useState({});
  const [error, setError] = useState("");
  const [direction, setDirection] = useState(1);
  const [isComplete, setIsComplete] = useState(false);
  const inputRef = useRef(null);

  const step = steps[currentStep];
  const isLastStep = currentStep === steps.length - 1;

  useEffect(() => {
    if (step?.type !== "options" && inputRef.current) {
      inputRef.current.focus();
    }
  }, [currentStep]);

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

    setDirection(1);
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
        setDirection(1);
        setCurrentStep((prev) => prev + 1);
      }
    }, 300);
  };

  const progress = ((currentStep + 1) / steps.length) * 100;

  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <motion.div
        className="w-full max-w-lg"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      >
        {/* Progress bar */}
        <div className="mb-12 flex gap-2">
          {steps.map((_, i) => (
            <motion.div
              key={i}
              className="h-0.5 flex-1 rounded-full overflow-hidden"
              style={{ background: "rgba(255,255,255,0.1)" }}
            >
              <motion.div
                className="h-full rounded-full"
                style={{ background: "var(--color-primary)" }}
                initial={{ width: 0 }}
                animate={{
                  width: i < currentStep ? "100%" : i === currentStep ? "100%" : "0%",
                }}
                transition={{ duration: 0.4, ease: "easeOut" }}
              />
            </motion.div>
          ))}
        </div>

        {/* Step content */}
        <div className="relative min-h-[200px]">
          <AnimatePresence mode="wait" custom={direction}>
            <motion.div
              key={currentStep}
              custom={direction}
              variants={slideVariants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.3, ease: "easeInOut" }}
              className="absolute inset-0"
            >
              <motion.label
                className="block font-heading text-3xl font-semibold mb-8"
                style={{ color: "var(--color-foreground)" }}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 }}
              >
                {step.label}
              </motion.label>

              {step.type === "options" ? (
                <div className="flex flex-col gap-3">
                  {step.options.map((option) => (
                    <motion.button
                      key={option}
                      onClick={() => handleOptionSelect(option)}
                      className={cn(
                        "w-full px-6 py-4 rounded-lg text-left text-lg transition-all",
                        "border border-border hover:border-primary",
                        values[step.id] === option
                          ? "border-primary bg-primary/10"
                          : "bg-card"
                      )}
                      whileHover={{ scale: 1.01 }}
                      whileTap={{ scale: 0.99 }}
                    >
                      <div className="flex items-center justify-between">
                        <span>{option}</span>
                        {values[step.id] === option && (
                          <Check className="h-5 w-5 text-primary" />
                        )}
                      </div>
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
                      const val = step.type === "tel" ? e.target.value.replace(/[^\d]/g, "") : e.target.value;
                      setValues((prev) => ({ ...prev, [step.id]: val }));
                      setError("");
                    }}
                    onKeyDown={handleKeyDown}
                    placeholder={step.placeholder}
                    className={cn(
                      "w-full bg-transparent border-b-2 border-border px-0 py-4 text-xl",
                      "focus:outline-none focus:border-primary transition-colors placeholder:text-muted-foreground",
                      error && "border-destructive"
                    )}
                  />
                  <AnimatePresence>
                    {error && (
                      <motion.p
                        initial={{ opacity: 0, y: -5 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        className="text-destructive text-sm mt-2"
                      >
                        {error}
                      </motion.p>
                    )}
                  </AnimatePresence>
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Next button */}
        {!isComplete && step.type !== "options" && (
          <motion.button
            onClick={handleNext}
            disabled={!values[step.id]}
            className={cn(
              "mt-8 px-8 py-3 rounded-lg flex items-center gap-2 font-medium transition-all",
              values[step.id]
                ? "bg-primary text-primary-foreground hover:bg-accent"
                : "bg-muted text-muted-foreground cursor-not-allowed"
            )}
            whileHover={values[step.id] ? { scale: 1.02 } : {}}
            whileTap={values[step.id] ? { scale: 0.98 } : {}}
          >
            {isLastStep ? "Complete" : "Continue"}
            <ArrowRight className="h-4 w-4" />
          </motion.button>
        )}
      </motion.div>
    </div>
  );
}
