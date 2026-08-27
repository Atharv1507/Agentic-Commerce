import { motion } from "framer-motion";
import ProductCard from "./ProductCard";

export default function ProductGrid({ products, cart, onAddToCart }) {
  return (
    <motion.div
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      {products.map((product, i) => (
        <motion.div
          key={product.id}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.05 }}
        >
          <ProductCard
            product={product}
            inCart={cart.some((item) => item.id === product.id)}
            onAddToCart={onAddToCart}
          />
        </motion.div>
      ))}
    </motion.div>
  );
}
