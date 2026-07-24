import duckdb


def lineage_trace(conn: duckdb.DuckDBPyConnection, run_id: str, order_id: str) -> dict:
    """Shows one order's items as they appear at source vs. in this run's
    staging output, side by side, plus what the category *should* translate
    to according to the (unmodified) reference translation table. This is
    what lets the agent prove a discrepancy was introduced by the transform
    itself, not by the source data."""
    order = conn.execute(
        "SELECT order_id, order_status, order_purchase_timestamp FROM src_orders WHERE order_id = ?",
        [order_id],
    ).fetchone()
    if order is None:
        return {"error": f"No such order_id: {order_id}"}

    source_items = conn.execute(
        """
        SELECT oi.order_item_id, oi.product_id, oi.seller_id, oi.price, oi.freight_value,
               p.product_category_name, s.seller_state,
               t.product_category_name_english AS reference_translation
        FROM src_order_items oi
        JOIN src_products p ON p.product_id = oi.product_id
        LEFT JOIN src_sellers s ON s.seller_id = oi.seller_id
        LEFT JOIN src_category_translation t ON t.product_category_name = p.product_category_name
        WHERE oi.order_id = ?
        ORDER BY oi.order_item_id
        """,
        [order_id],
    ).fetchall()

    staging_items = conn.execute(
        """
        SELECT order_item_id, product_id, seller_id, price, freight_value,
               category_english, seller_state
        FROM stg_order_items_enriched
        WHERE run_id = ? AND order_id = ?
        ORDER BY order_item_id
        """,
        [run_id, order_id],
    ).fetchall()
    staging_by_item = {row[0]: row for row in staging_items}

    items = []
    for row in source_items:
        item_id, product_id, seller_id, price, freight, cat_pt, seller_state, ref_translation = row
        staging_row = staging_by_item.get(item_id)
        items.append({
            "order_item_id": item_id,
            "product_id": product_id,
            "source": {
                "price": price, "freight_value": freight,
                "product_category_name": cat_pt, "seller_state": seller_state,
                "reference_translation_of_category": ref_translation,
            },
            "staging_in_this_run": {
                "price": staging_row[3], "freight_value": staging_row[4],
                "category_english": staging_row[5], "seller_state": staging_row[6],
            } if staging_row else None,
        })

    return {
        "order_id": order[0], "order_status": order[1],
        "order_purchase_timestamp": str(order[2]),
        "items": items,
    }
