# Todo
- Create the endpoints fo this app route.
- Create the tables for this app(all tables should start with food_trade):
    - user_roles - roles of the users (string)
        - id
        - user_id
        - role
    - categories - categories of the food
        - id
        - name
        - slug
        - sort_order
        - is_active
        - created_at
        - updated_at
    - users - use the users table from the auth app
    - extended_user - extended user table. 
        - id
        - user_id
        - address
        - region
        - created_at
        - updated_at
    - product - products of the food
        - id
        - name
        - slug
        - category_id
        - price
        - description
        - image_url
        - unit
        - min_order
        - is_active
        - stock (will be updated when the product is ordered)
        - created_at
        - updated_at
    - orders - orders of the users
        - id
        - user_id
        - contact_phone
        - delivery_address
        - delivery_region
        - product_id
        - quantity
        - total_price
        - status
        - notes
        - created_at
        - updated_at
    - order_items - items of the orders
        - id
        - order_id
        - product_id
        - product_name
        - quantity
        - unit_price
        - created_at
        - updated_at
    - whatsapp_groups - whatsapp groups of the users
        - id
        - region
        - link
        - description
        - is_active
        - created_at
        - updated_at
- When the order is created, the stock should be updated. Use async with the update_product_stock function.
- Make sure you use my custom codes and utils functions for the database operations.

## Endpoints - all endpoints should start with /api/food_trade
- Create the endpoints based on this superbase codes.
"""
import { createServerFn } from "@tanstack/react-start";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { z } from "zod";

function publicClient(): SupabaseClient {
  return createClient(
    process.env.SUPABASE_URL!,
    process.env.SUPABASE_PUBLISHABLE_KEY!,
    { auth: { storage: undefined, persistSession: false, autoRefreshToken: false } },
  );
}

export type Category = { id: string; name: string; slug: string; sort_order: number };
export type Product = {
  id: string; name: string; slug: string; description: string | null;
  price_ghs: number; unit: string; min_order_qty: number; stock_qty: number;
  image_url: string | null; category_id: string | null;
  categories: { slug: string; name: string } | null;
};
export type WhatsappGroup = { id: string; region: string; invite_url: string | null; description: string | null; sort_order: number };

export const listCategories = createServerFn({ method: "GET" }).handler(async (): Promise<Category[]> => {
  const supabase = publicClient();
  const { data, error } = await supabase.from("categories").select("id, name, slug, sort_order").order("sort_order");
  if (error) throw new Error(error.message);
  return (data ?? []) as Category[];
});

export const listProducts = createServerFn({ method: "GET" })
  .inputValidator((i: { category?: string; q?: string } | undefined) =>
    z.object({ category: z.string().optional(), q: z.string().optional() }).parse(i ?? {}),
  )
  .handler(async ({ data }): Promise<Product[]> => {
    const supabase = publicClient();
    let query = supabase
      .from("products")
      .select("id, name, slug, description, price_ghs, unit, min_order_qty, stock_qty, image_url, category_id, categories:category_id(slug, name)")
      .eq("is_active", true)
      .order("name");

    if (data.category) {
      const { data: cat } = await supabase.from("categories").select("id").eq("slug", data.category).maybeSingle();
      if (cat) query = query.eq("category_id", (cat as { id: string }).id);
    }
    if (data.q && data.q.trim()) {
      query = query.ilike("name", `%${data.q.trim()}%`);
    }
    const { data: rows, error } = await query;
    if (error) throw new Error(error.message);
    return (rows ?? []) as unknown as Product[];
  });

export const getProductBySlug = createServerFn({ method: "GET" })
  .inputValidator((i: { slug: string }) => z.object({ slug: z.string() }).parse(i))
  .handler(async ({ data }): Promise<Product | null> => {
    const supabase = publicClient();
    const { data: row, error } = await supabase
      .from("products")
      .select("id, name, slug, description, price_ghs, unit, min_order_qty, stock_qty, image_url, category_id, categories:category_id(slug, name)")
      .eq("slug", data.slug)
      .eq("is_active", true)
      .maybeSingle();
    if (error) throw new Error(error.message);
    return (row ?? null) as unknown as Product | null;
  });

export const listWhatsappGroups = createServerFn({ method: "GET" }).handler(async (): Promise<WhatsappGroup[]> => {
  const supabase = publicClient();
  const { data, error } = await supabase
    .from("whatsapp_groups")
    .select("id, region, invite_url, description, sort_order")
    .eq("is_active", true)
    .order("sort_order");
  if (error) throw new Error(error.message);
  return (data ?? []) as WhatsappGroup[];
});

"""

"""
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import type { SupabaseClient } from "@supabase/supabase-js";
import { requireSupabaseAuth } from "@/integrations/supabase/auth-middleware";

const orderItemSchema = z.object({
  product_id: z.string().uuid(),
  qty: z.number().int().positive(),
});

const placeOrderSchema = z.object({
  contact_phone: z.string().min(5),
  delivery_region: z.string().min(1),
  delivery_address: z.string().optional().default(""),
  notes: z.string().optional().default(""),
  items: z.array(orderItemSchema).min(1),
});

export const placeOrder = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((i: unknown) => placeOrderSchema.parse(i))
  .handler(async ({ data, context }) => {
    const supabase = context.supabase as unknown as SupabaseClient;
    const userId = context.userId;

    const ids = data.items.map((i) => i.product_id);
    const { data: products, error: prodErr } = await supabase
      .from("products")
      .select("id, name, price_ghs, is_active")
      .in("id", ids);
    if (prodErr) throw new Error(prodErr.message);
    const prodMap = new Map(
      ((products ?? []) as Array<{ id: string; name: string; price_ghs: number; is_active: boolean }>).map((p) => [p.id, p]),
    );

    let total = 0;
    const rows = data.items.map((i) => {
      const p = prodMap.get(i.product_id);
      if (!p || !p.is_active) throw new Error("Product unavailable");
      const line = Number(p.price_ghs) * i.qty;
      total += line;
      return { product_id: p.id, product_name: p.name, qty: i.qty, unit_price_ghs: Number(p.price_ghs) };
    });

    const { data: order, error: ordErr } = await supabase
      .from("orders")
      .insert({
        user_id: userId,
        contact_phone: data.contact_phone,
        delivery_region: data.delivery_region,
        delivery_address: data.delivery_address,
        notes: data.notes,
        total_ghs: total,
      })
      .select("id")
      .single();
    if (ordErr) throw new Error(ordErr.message);

    const orderId = (order as { id: string }).id;
    const { error: itemsErr } = await supabase
      .from("order_items")
      .insert(rows.map((r) => ({ ...r, order_id: orderId })));
    if (itemsErr) throw new Error(itemsErr.message);

    return { orderId, total };
  });

export type MyOrder = {
  id: string; status: string; total_ghs: number; created_at: string; delivery_region: string | null;
  order_items: Array<{ id: string; product_name: string; qty: number; unit_price_ghs: number }>;
};

export const getMyOrders = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }): Promise<MyOrder[]> => {
    const supabase = context.supabase as unknown as SupabaseClient;
    const { data, error } = await supabase
      .from("orders")
      .select("id, status, total_ghs, created_at, delivery_region, order_items(id, product_name, qty, unit_price_ghs)")
      .eq("user_id", context.userId)
      .order("created_at", { ascending: false });
    if (error) throw new Error(error.message);
    return (data ?? []) as unknown as MyOrder[];
  });

"""

"""
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import type { SupabaseClient } from "@supabase/supabase-js";
import { requireSupabaseAuth } from "@/integrations/supabase/auth-middleware";

async function assertAdmin(supabase: SupabaseClient, userId: string) {
  const { data, error } = await supabase
    .from("user_roles")
    .select("role")
    .eq("user_id", userId)
    .eq("role", "admin")
    .maybeSingle();
  if (error) throw new Error(error.message);
  if (!data) throw new Error("Forbidden: admin only");
}

export const isCurrentUserAdmin = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const supabase = context.supabase as unknown as SupabaseClient;
    const { data } = await supabase
      .from("user_roles")
      .select("role")
      .eq("user_id", context.userId)
      .eq("role", "admin")
      .maybeSingle();
    return { isAdmin: !!data };
  });

export type AdminProduct = {
  id: string; name: string; slug: string; description: string | null;
  price_ghs: number; unit: string; min_order_qty: number; stock_qty: number;
  is_active: boolean; category_id: string | null;
};

export const adminListProducts = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }): Promise<AdminProduct[]> => {
    const supabase = context.supabase as unknown as SupabaseClient;
    await assertAdmin(supabase, context.userId);
    const { data, error } = await supabase
      .from("products")
      .select("id, name, slug, description, price_ghs, unit, min_order_qty, stock_qty, is_active, category_id")
      .order("name");
    if (error) throw new Error(error.message);
    return (data ?? []) as AdminProduct[];
  });

const productInput = z.object({
  id: z.string().uuid().optional(),
  name: z.string().min(1),
  slug: z.string().min(1),
  description: z.string().optional().default(""),
  price_ghs: z.number().nonnegative(),
  unit: z.string().min(1),
  min_order_qty: z.number().int().positive(),
  stock_qty: z.number().int().nonnegative(),
  is_active: z.boolean(),
  category_id: z.string().uuid().nullable().optional(),
});

export const adminUpsertProduct = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((i: unknown) => productInput.parse(i))
  .handler(async ({ data, context }) => {
    const supabase = context.supabase as unknown as SupabaseClient;
    await assertAdmin(supabase, context.userId);
    const { error } = await supabase.from("products").upsert(data);
    if (error) throw new Error(error.message);
    return { ok: true };
  });

export const adminDeleteProduct = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((i: { id: string }) => z.object({ id: z.string().uuid() }).parse(i))
  .handler(async ({ data, context }) => {
    const supabase = context.supabase as unknown as SupabaseClient;
    await assertAdmin(supabase, context.userId);
    const { error } = await supabase.from("products").delete().eq("id", data.id);
    if (error) throw new Error(error.message);
    return { ok: true };
  });

export type AdminOrder = {
  id: string; user_id: string; status: string; total_ghs: number;
  contact_phone: string | null; delivery_region: string | null; delivery_address: string | null;
  notes: string | null; created_at: string;
  order_items: Array<{ id: string; product_name: string; qty: number; unit_price_ghs: number }>;
};

export const adminListOrders = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }): Promise<AdminOrder[]> => {
    const supabase = context.supabase as unknown as SupabaseClient;
    await assertAdmin(supabase, context.userId);
    const { data, error } = await supabase
      .from("orders")
      .select("id, user_id, status, total_ghs, contact_phone, delivery_region, delivery_address, notes, created_at, order_items(id, product_name, qty, unit_price_ghs)")
      .order("created_at", { ascending: false });
    if (error) throw new Error(error.message);
    return (data ?? []) as unknown as AdminOrder[];
  });

export const adminUpdateOrderStatus = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((i: { id: string; status: string }) =>
    z.object({
      id: z.string().uuid(),
      status: z.enum(["pending", "confirmed", "shipped", "delivered", "cancelled"]),
    }).parse(i),
  )
  .handler(async ({ data, context }) => {
    const supabase = context.supabase as unknown as SupabaseClient;
    await assertAdmin(supabase, context.userId);
    const { error } = await supabase.from("orders").update({ status: data.status }).eq("id", data.id);
    if (error) throw new Error(error.message);
    return { ok: true };
  });

export type AdminWhatsapp = { id: string; region: string; invite_url: string | null; description: string | null; is_active: boolean; sort_order: number };

export const adminListWhatsapp = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }): Promise<AdminWhatsapp[]> => {
    const supabase = context.supabase as unknown as SupabaseClient;
    await assertAdmin(supabase, context.userId);
    const { data, error } = await supabase
      .from("whatsapp_groups")
      .select("id, region, invite_url, description, is_active, sort_order")
      .order("sort_order");
    if (error) throw new Error(error.message);
    return (data ?? []) as AdminWhatsapp[];
  });

export const adminUpdateWhatsapp = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((i: { id: string; invite_url: string; is_active: boolean }) =>
    z.object({ id: z.string().uuid(), invite_url: z.string(), is_active: z.boolean() }).parse(i),
  )
  .handler(async ({ data, context }) => {
    const supabase = context.supabase as unknown as SupabaseClient;
    await assertAdmin(supabase, context.userId);
    const { error } = await supabase
      .from("whatsapp_groups")
      .update({ invite_url: data.invite_url || null, is_active: data.is_active })
      .eq("id", data.id);
    if (error) throw new Error(error.message);
    return { ok: true };
  });

export const adminListCategories = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const supabase = context.supabase as unknown as SupabaseClient;
    await assertAdmin(supabase, context.userId);
    const { data, error } = await supabase
      .from("categories")
      .select("id, name, slug, sort_order")
      .order("sort_order");
    if (error) throw new Error(error.message);
    return (data ?? []) as Array<{ id: string; name: string; slug: string; sort_order: number }>;
  });
"""
- CREATE AN ENDPOINT FOR VERIFY THE USER AFTER THE USER LOGGING IN. ITS JUST CHECK THE USER AUTHENTICATED IF HE IS IN THE EXTENDED USER AND USER ROLES. IF NOT CREATE THEM FOR IT AND SET THIER ROLES TO "user". the users maybe in in the users tables but have not lin the food_trades roles or extended users. 

# Note
- Finish all the task in this readme file.